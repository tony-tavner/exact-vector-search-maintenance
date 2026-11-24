#include <stdint.h>
#include <stddef.h>
#include <fenv.h>
#include <Python.h>
/* Read-only audit helper. Does not change FPCR or the rounding environment. */
uint64_t c1_read_fpcr(void) {
    uint64_t x;
    __asm__ volatile ("mrs %0, fpcr" : "=r" (x));
    return x;
}
int c1_rounding(void) { return fegetround(); }
int c1_nearest_constant(void) { return FE_TONEAREST; }
size_t c1_number_offset(void) { return offsetof(PyTypeObject, tp_as_number); }
size_t c1_multiply_offset(void) { return offsetof(PyNumberMethods, nb_multiply); }
