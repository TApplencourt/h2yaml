typedef float float4 __attribute__((vector_size(16)));
typedef int int2 __attribute__((ext_vector_type(2)));
typedef float cl_float;
typedef cl_float __cl_float4 __attribute__((vector_size(4 * sizeof(cl_float))));
typedef union {
  cl_float s[4];
  __cl_float4 v4;
} cl_float4;
struct s {
  int2 a;
  float4 b[2];
};
cl_float f(cl_float4 a, const int2 *b);
