#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <arm_neon.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
static PyObject *canonical_fsum = NULL;
static uint64_t fpcr_value(void) {uint64_t x; __asm__ volatile("mrs %0, fpcr":"=r"(x)); return x;}
static PyObject *read_fpcr(PyObject *s, PyObject *a) {return PyLong_FromUnsignedLongLong(fpcr_value());}
static PyObject *same_fsum(PyObject *s, PyObject *obj) {return PyBool_FromLong(obj==canonical_fsum);}
static PyObject *matrix(PyObject *self, PyObject *args) {
    PyObject *qo,*xo,*result=NULL,*terms=NULL,*value=NULL;
    Py_buffer q={0},x={0};
    if (!PyArg_ParseTuple(args,"OO",&qo,&xo)) return NULL;
    if (fpcr_value()!=0) {PyErr_SetString(PyExc_RuntimeError,"unsupported_fpcr");return NULL;}
    if (PyObject_GetBuffer(qo,&q,PyBUF_C_CONTIGUOUS|PyBUF_FORMAT)<0) return NULL;
    if (PyObject_GetBuffer(xo,&x,PyBUF_C_CONTIGUOUS|PyBUF_FORMAT)<0) goto done;
    if (q.ndim!=2 || x.ndim!=2 || q.itemsize!=8 || x.itemsize!=8 ||
        strcmp(q.format,"d") || strcmp(x.format,"d") || q.shape[1]!=x.shape[1] || q.shape[1]<1) {
        PyErr_SetString(PyExc_ValueError,"expected_contiguous_native_float64_matrices");goto done;
    }
    Py_ssize_t nq=q.shape[0],nx=x.shape[0],p=q.shape[1];
    if (nx && nq>PY_SSIZE_T_MAX/8/nx) {PyErr_SetString(PyExc_OverflowError,"matrix_too_large");goto done;}
    result=PyBytes_FromStringAndSize(NULL,nq*nx*8);if(!result) goto done;
    double *out=(double *)PyBytes_AS_STRING(result);
    const double *qv=(const double *)q.buf,*xv=(const double *)x.buf;
    for(Py_ssize_t i=0;i<nq;i++) for(Py_ssize_t j=0;j<nx;j++) {
        terms=PyTuple_New(p);if(!terms) goto fail;
        Py_ssize_t k=0;
        for(;k+1<p;k+=2) {
            double ab[2];
            vst1q_f64(ab,vmulq_f64(vld1q_f64(qv+i*p+k),vld1q_f64(xv+j*p+k)));
            PyObject *a=PyFloat_FromDouble(ab[0]),*b=PyFloat_FromDouble(ab[1]);
            if(!a || !b){Py_XDECREF(a);Py_XDECREF(b);goto fail;}
            PyTuple_SET_ITEM(terms,k,a);PyTuple_SET_ITEM(terms,k+1,b);
        }
        if(k<p){double ab=qv[i*p+k]*xv[j*p+k];PyObject *a=PyFloat_FromDouble(ab);if(!a)goto fail;PyTuple_SET_ITEM(terms,k,a);}
        /* Call the actual pinned builtin on plain floats, in coordinate order.
           No replacement summation, BLAS reduction, FMA, or released GIL. */
        value=PyObject_CallOneArg(canonical_fsum,terms);Py_CLEAR(terms);if(!value)goto fail;
        double score=PyFloat_AsDouble(value);Py_CLEAR(value);
        if(PyErr_Occurred())goto fail;
        if(!isfinite(score)){PyErr_SetString(PyExc_ValueError,"nonfinite_score");goto fail;}
        out[i*nx+j]=score;
    }
    if(fpcr_value()!=0){PyErr_SetString(PyExc_RuntimeError,"changed_fpcr");goto fail;}
    goto done;
fail: Py_CLEAR(result);
done: Py_XDECREF(terms);Py_XDECREF(value);if(x.obj)PyBuffer_Release(&x);if(q.obj)PyBuffer_Release(&q);return result;
}
static PyMethodDef methods[]={
 {"matrix",matrix,METH_VARARGS,"Native binary64 SIMD products, actual math.fsum per pair."},
 {"read_fpcr",read_fpcr,METH_NOARGS,"Read ARM64 FPCR, without changing it."},
 {"same_fsum",same_fsum,METH_O,"Check callable identity against the pinned builtin."},
 {NULL,NULL,0,NULL}};
static struct PyModuleDef module={PyModuleDef_HEAD_INIT,"_native",NULL,-1,methods};
PyMODINIT_FUNC PyInit__native(void) {
 PyObject *m=PyImport_ImportModule("math");if(!m)return NULL;
 canonical_fsum=PyObject_GetAttrString(m,"fsum");Py_DECREF(m);if(!canonical_fsum)return NULL;
 if(!PyCFunction_Check(canonical_fsum)){Py_CLEAR(canonical_fsum);PyErr_SetString(PyExc_RuntimeError,"fsum_not_builtin");return NULL;}
 return PyModule_Create(&module);
}
