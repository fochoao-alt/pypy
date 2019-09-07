from rpython.rtyper.lltypesystem import lltype, llmemory
from rpython.rtyper.lltypesystem import rffi
from rpython.memory.gc.rrc.base import RawRefCountBaseGC
from rpython.rlib.debug import ll_assert, debug_print, debug_start, debug_stop

class RawRefCountIncMarkGC(RawRefCountBaseGC):

    def major_collection_trace_step(self):
        if not self.cycle_enabled or self.state == self.STATE_GARBAGE:
            self._debug_check_consistency(print_label="begin-mark")
            self.p_list_old.foreach(self._major_trace, (False, False))
            self._debug_check_consistency(print_label="end-mark")
            return True

        if self.state == self.STATE_DEFAULT:
            # For all non-gc pyobjects which have a refcount > 0,
            # mark all reachable objects on the pypy side
            self.p_list_old.foreach(self._major_trace_nongc, False)
            # TODO: execute incrementally (own phase)

            # Merge all objects whose finalizer have been executed to the
            # pyobj_list (to reprocess them again in the snapshot). Finalizers
            # can only be executed once, so termination will eventually happen.
            # Objects which have not been resurrected should be freed during
            # this cycle.
            if not self._gc_list_is_empty(self.pyobj_old_list):
                self._gc_list_merge(self.pyobj_old_list, self.pyobj_list)
            # TODO: take snapshot of pyobj_old_list and perform _collect_roots
            #       incrementally (own phase)

            # Untrack all tuples with only non-gc rrc objects and
            # promote all other tuples to the pyobj_list
            self._untrack_tuples()
            # TODO: execute incrementally? (before snapshot!, own phase)

            # Now take a snapshot
            self._take_snapshot(self.pyobj_list)

            # collect all rawrefcounted roots
            self._collect_roots()
            # TODO: execute incrementally (own phase, save index)

            self._debug_check_consistency(print_label="roots-marked")
            self.state = self.STATE_MARKING
            return False

        if self.state == self.STATE_MARKING:
            # mark all objects reachable from rawrefcounted roots
            all_rrc_marked = self._mark_rawrefcount()
            # TODO: execute incrementally

            if (all_rrc_marked and not self.gc.objects_to_trace.non_empty() and
                    not self.gc.more_objects_to_trace.non_empty()):
                # all objects have been marked, dead objects will stay dead
                self._debug_check_consistency(print_label="before-fin")
                self.state = self.STATE_GARBAGE_MARKING

            return False

        # we are finished with marking, now finish things up
        ll_assert(self.state == self.STATE_GARBAGE_MARKING, "invalid state")

        # sync snapshot with pyob_list:
        #  * check the consistency of "dead" objects and keep all of them
        #    alive, in case an inconsistency is found (the graph changed
        #    between two pauses, so some of those objects might be alive)
        #  * move all dead objects still in pyob_list to pyobj_old_list
        #  * for all other objects (in snapshot and new),
        #    set their cyclic refcount to > 0 to mark them as live
        pygchdr = self.pyobj_list.c_gc_next
        consistent = True
        self.snapshot_consistent = True
        while pygchdr <> self.pyobj_list:
            next_old = pygchdr.c_gc_next
            if pygchdr.c_gc_refs > 0: # object is in snapshot
                snapobj = self.snapshot_objs[pygchdr.c_gc_refs - 1]
                pygchdr.c_gc_refs = snapobj.refcnt_external
                if snapobj.refcnt_external == 0: # object considered dead
                    # check consistency (dead subgraphs can never change):
                    pyobj = self.gc_as_pyobj(pygchdr)
                    # refcount equal
                    consistent = snapobj.refcnt == pyobj.c_ob_refcnt
                    if not consistent:
                        break
                    # outgoing (internal) references equal
                    self.snapshot_curr = snapobj
                    self.snapshot_curr_index = 0
                    self._check_snapshot_traverse(pyobj)
                    consistent = self.snapshot_consistent
                    if not consistent:
                        break
                    # consistent -> prepare object for collection
                    self._gc_list_remove(pygchdr)
                    self._gc_list_add(self.pyobj_old_list, pygchdr)
            else:
                pygchdr.c_gc_refs = 1 # new object, keep alive
            pygchdr = next_old

        self._debug_check_consistency(print_label="end-check-consistency")

        if not consistent:  # keep all objects alive
            while pygchdr <> self.pyobj_list: # continue previous loop
                pygchdr.c_gc_refs = 1
                pygchdr = pygchdr.c_gc_next
            pygchdr = self.pyobj_old_list.c_gc_next
            while pygchdr <> self.pyobj_old_list: # resurrect "dead" objects
                pygchdr.c_gc_refs = 1
                pygchdr = pygchdr.c_gc_next
            if not self._gc_list_is_empty(self.pyobj_old_list):
                self._gc_list_merge(self.pyobj_old_list, self.pyobj_list)

        self._debug_check_consistency(print_label="before-snap-discard")

        # now the snapshot is not needed any more, discard it
        self._discard_snapshot()

        # handle legacy finalizers (assumption: not a lot of legacy finalizers,
        # so no need to do it incrementally)
        if self._find_garbage(False):
            self._mark_garbage(False)
            self._debug_check_consistency(print_label="end-legacy-fin")
        self.state = self.STATE_DEFAULT

        # handle modern finalizers
        found_finalizer = self._find_finalizer()
        if found_finalizer:
            self._gc_list_move(self.pyobj_old_list, self.pyobj_isolate_list)
        use_cylicrc = not found_finalizer

        # now mark all pypy objects at the border, depending on the results
        self._debug_check_consistency(print_label="end-mark-cyclic")
        debug_print("use_cylicrc", use_cylicrc)
        self.p_list_old.foreach(self._major_trace, (use_cylicrc, False))
        self._debug_check_consistency(print_label="end-mark")
        return True

    def _collect_roots(self):
        # Subtract all internal refcounts from the cyclic refcount
        # of rawrefcounted objects
        for i in range(0, self.total_objs):
            obj = self.snapshot_objs[i]
            for j in range(0, obj.refs_len):
                addr = self.snapshot_refs[obj.refs_index + j]
                obj_ref = llmemory.cast_adr_to_ptr(addr,
                                                   self.PYOBJ_SNAPSHOT_OBJ_PTR)
                obj_ref.refcnt_external -= 1

        # now all rawrefcounted roots or live border objects have a
        # refcount > 0

    def _mark_rawrefcount(self):
        self._gc_list_init(self.pyobj_old_list)
        # as long as new objects with cyclic a refcount > 0 or alive border
        # objects are found, increment the refcount of all referenced objects
        # of those newly found objects
        reached_limit = False
        found_alive = True
        simple_limit = 0
        #
        while found_alive and not reached_limit: # TODO: working set to improve performance?
            found_alive = False
            for i in range(0, self.total_objs):
                obj = self.snapshot_objs[i]
                found_alive |= self._mark_rawrefcount_obj(obj)
            simple_limit += 1
            if simple_limit > 3: # TODO: implement sane limit
                reached_limit
        return not reached_limit # are there any objects left?

    def _mark_rawrefcount_obj(self, snapobj):
        if snapobj.status == 0: # already processed
            return False

        alive = snapobj.refcnt_external > 0
        if snapobj.pypy_link <> 0:
            intobj = snapobj.pypy_link
            obj = llmemory.cast_int_to_adr(intobj)
            if not alive and self.gc.header(obj).tid & (
                    self.GCFLAG_VISITED | self.GCFLAG_NO_HEAP_PTRS):
                alive = True
                snapobj.refcnt_external += 1
        if alive:
            # increment refcounts
            for j in range(0, snapobj.refs_len):
                addr = self.snapshot_refs[snapobj.refs_index + j]
                obj_ref = llmemory.cast_adr_to_ptr(addr,
                                                   self.PYOBJ_SNAPSHOT_OBJ_PTR)
                obj_ref.refcnt_external += 1
            # mark recursively, if it is a pypyobj
            if snapobj.pypy_link <> 0:
                intobj = snapobj.pypy_link
                obj = llmemory.cast_int_to_adr(intobj)
                self.gc.objects_to_trace.append(obj)
                self.gc.visit_all_objects()  # TODO: remove to improve pause times
            # mark as processed
            snapobj.status = 0
        return alive

    def _take_snapshot(self, pygclist):
        from rpython.rlib.rawrefcount import REFCNT_FROM_PYPY
        from rpython.rlib.rawrefcount import REFCNT_FROM_PYPY_LIGHT
        #
        total_refcnt = 0
        total_objs = 0
        pygchdr = pygclist.c_gc_next
        while pygchdr <> pygclist:
            refcnt = self.gc_as_pyobj(pygchdr).c_ob_refcnt
            if refcnt >= REFCNT_FROM_PYPY_LIGHT:
                refcnt -= REFCNT_FROM_PYPY_LIGHT
            elif refcnt >= REFCNT_FROM_PYPY:
                refcnt -= REFCNT_FROM_PYPY
            total_refcnt += refcnt
            total_objs += 1
            pygchdr = pygchdr.c_gc_next
        self.snapshot_refs = lltype.malloc(self._ADDRARRAY, total_refcnt,
                                           flavor='raw',
                                           track_allocation=False)
        self.snapshot_objs = lltype.malloc(self.PYOBJ_SNAPSHOT, total_objs,
                                           flavor='raw',
                                           track_allocation=False)
        self.total_objs = total_objs

        objs_index = 0
        refs_index = 0
        pygchdr = pygclist.c_gc_next
        while pygchdr <> pygclist:
            pyobj = self.gc_as_pyobj(pygchdr)
            refcnt = pyobj.c_ob_refcnt
            if refcnt >= REFCNT_FROM_PYPY_LIGHT:
                refcnt -= REFCNT_FROM_PYPY_LIGHT
            elif refcnt >= REFCNT_FROM_PYPY:
                refcnt -= REFCNT_FROM_PYPY
            if pyobj.c_ob_pypy_link != 0:
                addr = llmemory.cast_int_to_adr(pyobj.c_ob_pypy_link)
                if self.gc.header(addr).tid & (self.GCFLAG_VISITED |
                                              self.GCFLAG_NO_HEAP_PTRS):
                    refcnt += 1
            pygchdr.c_gc_refs = objs_index + 1
            obj = self.snapshot_objs[objs_index]
            obj.pyobj = llmemory.cast_ptr_to_adr(pyobj)
            obj.status = 1
            obj.refcnt = pyobj.c_ob_refcnt
            obj.refcnt_external = refcnt
            obj.refs_index = refs_index
            obj.refs_len = 0
            obj.pypy_link = pyobj.c_ob_pypy_link
            self.snapshot_curr = obj
            self._take_snapshot_traverse(pyobj)
            objs_index += 1
            refs_index += obj.refs_len
            pygchdr = pygchdr.c_gc_next
        for i in range(0, refs_index):
            addr = self.snapshot_refs[i]
            pyobj = llmemory.cast_adr_to_ptr(addr, self.PYOBJ_GC_HDR_PTR)
            obj = self.snapshot_objs[pyobj.c_gc_refs - 1]
            self.snapshot_refs[i] = llmemory.cast_ptr_to_adr(obj)

    def _take_snapshot_visit(pyobj, self_ptr):
        from rpython.rtyper.annlowlevel import cast_adr_to_nongc_instance
        #
        self_adr = rffi.cast(llmemory.Address, self_ptr)
        self = cast_adr_to_nongc_instance(RawRefCountIncMarkGC, self_adr)
        self._take_snapshot_visit_action(pyobj, None)
        return rffi.cast(rffi.INT_real, 0)

    def _take_snapshot_visit_action(self, pyobj, ignore):
        pygchdr = self.pyobj_as_gc(pyobj)
        if pygchdr <> lltype.nullptr(self.PYOBJ_GC_HDR) and \
                pygchdr.c_gc_refs != self.RAWREFCOUNT_REFS_UNTRACKED:
            curr = self.snapshot_curr
            index = curr.refs_index + curr.refs_len
            self.snapshot_refs[index] = llmemory.cast_ptr_to_adr(pygchdr)
            curr.refs_len += 1

    def _take_snapshot_traverse(self, pyobj):
        from rpython.rlib.objectmodel import we_are_translated
        from rpython.rtyper.annlowlevel import (cast_nongc_instance_to_adr,
                                                llhelper)
        #
        if we_are_translated():
            callback_ptr = llhelper(self.RAWREFCOUNT_VISIT,
                                    RawRefCountIncMarkGC._take_snapshot_visit)
            self_ptr = rffi.cast(rffi.VOIDP, cast_nongc_instance_to_adr(self))
            self.tp_traverse(pyobj, callback_ptr, self_ptr)
        else:
            self.tp_traverse(pyobj, self._take_snapshot_visit_action, None)

    def _check_snapshot_visit(pyobj, self_ptr):
        from rpython.rtyper.annlowlevel import cast_adr_to_nongc_instance
        #
        self_adr = rffi.cast(llmemory.Address, self_ptr)
        self = cast_adr_to_nongc_instance(RawRefCountIncMarkGC, self_adr)
        self._check_snapshot_visit_action(pyobj, None)
        return rffi.cast(rffi.INT_real, 0)

    def _check_snapshot_visit_action(self, pyobj, ignore):
        pygchdr = self.pyobj_as_gc(pyobj)
        if pygchdr <> lltype.nullptr(self.PYOBJ_GC_HDR) and \
                pygchdr.c_gc_refs != self.RAWREFCOUNT_REFS_UNTRACKED:
            # check consistency with snapshot
            curr = self.snapshot_curr
            curr_index = self.snapshot_curr_index
            if curr_index < curr.refs_len:
                # ref changed? -> issue, if traversal order is not stable!!!
                index = curr.refs_index + curr_index
                ref_addr = self.snapshot_refs[index]
                ref = llmemory.cast_adr_to_ptr(ref_addr,
                                               self.PYOBJ_SNAPSHOT_OBJ_PTR)
                old_value = ref.pyobj
                new_value = llmemory.cast_ptr_to_adr(pyobj)
                if old_value != new_value:
                    self.snapshot_consistent = False # reference changed
            else:
                self.snapshot_consistent = False # references added
            self.snapshot_curr_index += 1

    def _check_snapshot_traverse(self, pyobj):
        from rpython.rlib.objectmodel import we_are_translated
        from rpython.rtyper.annlowlevel import (cast_nongc_instance_to_adr,
                                                llhelper)
        #
        if we_are_translated():
            callback_ptr = llhelper(self.RAWREFCOUNT_VISIT,
                                    RawRefCountIncMarkGC._check_snapshot_visit)
            self_ptr = rffi.cast(rffi.VOIDP, cast_nongc_instance_to_adr(self))
            self.tp_traverse(pyobj, callback_ptr, self_ptr)
        else:
            self.tp_traverse(pyobj, self._check_snapshot_visit_action, None)

    def _discard_snapshot(self):
        lltype.free(self.snapshot_objs, flavor='raw', track_allocation=False)
        lltype.free(self.snapshot_refs, flavor='raw', track_allocation=False)