from pypy.interpreter.typedef import TypeDef
from pypy.interpreter.gateway import interp2app
from pypy.interpreter.baseobjspace import W_Root
from pypy.interpreter.error import OperationError

from prolog.interpreter import continuation
from prolog.interpreter import error
from prolog.interpreter import parsing
from prolog.interpreter import term

import pypy.module.unipycation.util as util
from pypy.module.unipycation import objects, conversion

from rpython.rlib.streamio import open_file_as_stream
from rpython.rlib import rstring

class W_CoreSolutionIterator(W_Root):
    """
    An interface that allows retrieval of multiple solutions
    """

    def __init__(self, space, w_unbound_vars, w_goal_term, w_engine):
        self.w_engine = w_engine
        self.w_unbound_vars = w_unbound_vars

        w_goal_term = space.interp_w(objects.W_Term, w_goal_term)
        self.w_goal_term = w_goal_term

        self.space = space

        # The state of the prolog interpreter continuation.
        # Used for enumerating results.
        self.fcont = None
        self.heap = None

    def _store_fcont_heap(self, fcont, heap):
        self.fcont = fcont
        self.heap = heap

    def _create_result(self, w_unbound_vars):
        """ Called internally after the activation of the continuation """
        w_result = self.space.newdict()

        for w_var in self.space.listview(w_unbound_vars):
            w_var = self.space.interp_w(objects.W_Var, w_var)

            w_binding = conversion.w_of_p(
                self.space, w_var.p_var.dereference(None))
            self.space.setitem(w_result, w_var, w_binding)
        return w_result

    def iter_w(self): return self

    def next_w(self):
        """ Obtain the next solution (if there is one) """


        p_goal_term = cur_mod = cont = None

        first_iteration = self.fcont is None
        if first_iteration:
            # The first iteration is special. Here we set up the continuation
            # for subsequent iterations.
            cur_mod = self.w_engine.engine.modulewrapper.current_module
            cont = UnipycationContinuation(
                    self.w_engine, self)
            p_goal_term = self.w_goal_term.p_term
            self.w_goal_term = None # allow GC
        try:
            if first_iteration:
                r = self.w_engine.engine.run(p_goal_term, cur_mod, cont)
            else:
                continuation.driver(*self.fcont.fail(self.heap))
        except error.UnificationFailed:
            # contradiction - no solutions
            raise OperationError(self.space.w_StopIteration, self.space.w_None)
        except (error.CatchableError, error.UncaughtError) as ex:
            w_PrologError = util.get_from_module(self.space, "unipycation", "PrologError")
            engine = self.w_engine.engine
            raise OperationError(w_PrologError, self.space.wrap(ex.get_errstr(engine)))

        return self._create_result(self.w_unbound_vars)

W_CoreSolutionIterator.typedef = TypeDef("CoreSolutionIterator",
    __iter__ = interp2app(W_CoreSolutionIterator.iter_w),
    next = interp2app(W_CoreSolutionIterator.next_w),
)

W_CoreSolutionIterator.typedef.acceptable_as_base_class = False

# ---

class UnipycationContinuation(continuation.Continuation):
    def __init__(self, w_engine, w_solution_iter):
        p_engine = w_engine.engine

        continuation.Continuation.__init__(self,
                p_engine, continuation.DoneSuccessContinuation(p_engine))

        # stash
        self.w_engine = w_engine
        self.w_solution_iter = w_solution_iter

    def activate(self, fcont, heap):
        self.w_solution_iter._store_fcont_heap(fcont, heap)
        return continuation.DoneSuccessContinuation(self.engine), fcont, heap

# ---

def engine_new__(space, w_subtype, __args__):
    w_anything = __args__.firstarg()
    e = W_CoreEngine(space, w_anything)
    return space.wrap(e)

class W_CoreEngine(W_Root):
    def __init__(self, space, w_anything):
        self.space = space                      # Stash space
        self.engine = e = continuation.Engine(load_system=True) # We embed an instance of prolog

        try:
            e.runstring(space.str_w(w_anything))# Load the database with the first arg
        except parsing.ParseError as e:
            w_ParseError = util.get_from_module(self.space, "unipycation", "ParseError")
            raise OperationError(w_ParseError, self.space.wrap(e.nice_error_message()))

    @staticmethod
    def from_file(space, w_cls, w_filename):
        filename = space.str0_w(w_filename)

        # have to use rpython io
        hndl = open_file_as_stream(filename)
        prog = db = hndl.readall()
        hndl.close()

        return space.wrap(W_CoreEngine(space, space.wrap(db)))

    def query_iter(self, w_goal_term, w_unbound_vars):
        """ Returns an iterator by which to acquire multiple solutions """
        return W_CoreSolutionIterator(self.space, w_unbound_vars, w_goal_term, self)

    def query_single(self, w_goal_term, w_unbound_vars):
        try:
            return self.query_iter(w_goal_term, w_unbound_vars).next_w()
        except OperationError, e:
            if not e.match(self.space, self.space.w_StopIteration):
                raise
            return self.space.w_None

W_CoreEngine.typedef = TypeDef("CoreEngine",
    __new__ = interp2app(engine_new__),
    from_file = interp2app(W_CoreEngine.from_file, as_classmethod=True),
    query_iter = interp2app(W_CoreEngine.query_iter),
    query_single = interp2app(W_CoreEngine.query_single),
)

W_CoreEngine.typedef.acceptable_as_base_class = False
