import sys
import operator

from pypy.interpreter.baseobjspace \
     import ObjSpace, OperationError, NoValue, PyPyError
from pypy.interpreter.pycode import PyByteCode


class W_Object(object):
    pass

class W_Anything(W_Object):
    pass

class W_Integer(W_Object):
    pass

class W_Constant(W_Object):
    def __init__(self, value):
        self.value = value
    def __repr__(self):
        return '<constant %r>' % self.value

class W_KnownKeysContainer(W_Object):
    def __init__(self, args_w):
        self.args_w = args_w
    def __len__(self):
        return len(self.args_w)
    def __getitem__(self, i):
        return self.args_w[i]


class AnnException(Exception):
    pass


class AnnotationObjSpace(ObjSpace):

    def initialize(self):
        self.w_None = self.wrap(None)
        self.w_True = self.wrap(True)
        self.w_False = self.wrap(False)
        self.w_NotImplemented = self.wrap(NotImplemented)
        self.w_Ellipsis = self.wrap(Ellipsis)
        import __builtin__, types
        for n, c in __builtin__.__dict__.iteritems():
            if isinstance(c, (types.TypeType, Exception)):
                setattr(self, 'w_' + c.__name__, self.wrap(c))
        self.w_builtins = self.wrap(__builtin__)

    # Service methods

    def wrap(self, obj):
        return W_Constant(obj)

    def unwrap(self, w_obj):
        if isinstance(w_obj, W_Constant):
            return w_obj.value
        elif isinstance(w_obj, W_Object):
            raise AnnException, "Cannot unwrap %r" % w_obj
        else:
            raise TypeError, "not wrapped: %s" % repr(w_obj)

    def is_true(self, w_obj):
        if isinstance(w_obj, W_KnownKeysContainer):
            return bool(len(w_obj))
        obj = self.unwrap(w_obj)
        return bool(obj)

    def reraise(self):
        t, v = sys.exc_info()[:2]
        raise OperationError(self.wrap(t), self.wrap(v))

    # Specialized creators
    
    def newtuple(self, args_w):
        for w_arg in args_w:
            if not isinstance(w_arg, W_Constant):
                return W_KnownKeysContainer(args_w)
        return self.wrap(tuple(map(self.unwrap, args_w)))

    def newdict(self, items_w):
        values_w = {}
        for w_key, w_value in items_w:
            try:
                key = self.unwrap(w_key)
            except AnnException:
                break
            else:
                values_w[key] = w_value
        else:
            return W_KnownKeysContainer(values_w)
        return W_Anything()

    def newmodule(self, w_name):
        return W_Anything()

    def newfunction(self, *stuff):
        return W_Anything()

    # Methods implementing Python operations
    # (Many missing ones are added by make_op() below)

    def add(self, w_left, w_right):
        try:
            left = self.unwrap(w_left)
            right = self.unwrap(w_right)
        except AnnException:
            pass
        else:
            return self.wrap(left + right)
        if self.is_int(w_left) and self.is_int(w_right):
            return W_Integer()
        else:
            return W_Anything()

    def is_int(self, w_obj):
        if isinstance(w_obj, W_Integer):
            return True
        if isinstance(w_obj, W_Constant):
            return isinstance(w_obj.value, int)
        else:
            return False

    def call(self, w_func, w_args, w_kwds):
        func = self.unwrap(w_func) # Would be bad it it was W_Anything
        code = func.func_code
        bytecode = PyByteCode()
        bytecode._from_code(code)
        w_locals = bytecode.build_arguments(self,
                                            w_args,
                                            w_kwds,
                                            self.wrap(func.func_defaults),
                                            self.wrap(()))
        w_result = bytecode.eval_code(self,
                                      self.wrap(func.func_globals),
                                      w_locals)
        return w_result

    def getattr(self, w_obj, w_name):
        try:
            obj = self.unwrap(w_obj)
            name = self.unwrap(w_name)
        except AnnException:
            return W_Anything()
        else:
            try:
                return self.wrap(getattr(obj, name))
            except:
                return self.reraise()

    def len(self, w_obj):
        if isinstance(w_obj, W_KnownKeysContainer):
            return self.wrap(len(w_obj))
        try:
            obj = self.unwrap(w_obj)
        except AnnException:
            return W_Anything()
        else:
            return self.wrap(len(obj))

    def getitem(self, w_obj, w_key):
        try:
            key = self.unwrap(w_key)
        except AnnException:
            return W_Anything()
        try:
            obj = self.unwrap(w_obj)
        except AnnException:
            if isinstance(w_obj, W_KnownKeysContainer):
                return w_obj[key]
            else:
                return W_Anything()
        try:
            return self.wrap(obj[key])
        except:
            self.reraise()

def make_op(name, symbol, arity, specialnames):

    if not hasattr(operator, name):
        return # Can't do it

    if hasattr(AnnotationObjSpace, name):
        return # Shouldn't do it

    def generic_operator(space, *args_w):
        assert len(args_w) == arity, "got a wrong number of arguments"
        for w_arg in args_w:
            if not isinstance(w_arg, W_Constant):
                break
        else:
            # all arguments are constants, call the operator now
            op = getattr(operator, name)
            args = [space.unwrap(w_arg) for w_arg in args_w]
            result = op(*args)
            return space.wrap(result)

        return W_Anything()

    setattr(AnnotationObjSpace, name, generic_operator)

for line in ObjSpace.MethodTable:
    make_op(*line)
