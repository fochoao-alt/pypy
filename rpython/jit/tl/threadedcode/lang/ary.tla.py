from rpython.jit.tl.threadedcode import tla

code = [
    tla.CONST_N, 0, 0, 0, 50,
    tla.CONST_INT, 1,
    tla.DUP,
    tla.DUPN, 2,
    tla.BUILD_LIST,
    tla.CONST_INT, 2,
    tla.DUP,
    tla.DUPN, 4,
    tla.BUILD_LIST,
    tla.CONST_INT, 0,
    tla.DUP,
    tla.DUPN, 6,
    tla.BUILD_LIST,
    tla.CONST_INT, 0,
    tla.DUP,
    tla.DUPN, 8,
    tla.DUPN, 7,
    tla.DUPN, 6,
    tla.DUPN, 5,
    tla.CALL_ASSEMBLER, 54, 5,
    tla.DUP,
    tla.CONST_INT, 0,
    tla.LOAD,
    tla.DUP,
    tla.PRINT,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.EXIT,
    tla.DUPN, 4,
    tla.CONST_INT, 1,
    tla.SUB,
    tla.DUPN, 6,
    tla.DUPN, 1,
    tla.LT,
    tla.JUMP_IF, 70,
    tla.DUPN, 2,
    tla.JUMP, 116,
    tla.DUPN, 4,
    tla.DUPN, 7,
    tla.LOAD,
    tla.DUPN, 4,
    tla.DUPN, 8,
    tla.LOAD,
    tla.DUPN, 1,
    tla.DUPN, 1,
    tla.ADD,
    tla.DUP,
    tla.DUPN, 6,
    tla.DUPN, 11,
    tla.STORE,
    tla.DUPN, 10,
    tla.CONST_INT, 1,
    tla.ADD,
    tla.DUP,
    tla.DUPN, 11,
    tla.DUPN, 11,
    tla.DUPN, 11,
    tla.DUPN, 11,
    tla.FRAME_RESET, 5, 6, 5,
    tla.JUMP, 54,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.POP1,
    tla.RET, 5,
]
