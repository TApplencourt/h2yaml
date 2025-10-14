// ~=~=
// Hoist into "typedefs" section
// We Hoist non anonymous enum
// ~=~=

enum h_0e { h_0e_0 };

struct h_1s {
  enum h_1e { h_1e_0 } A_m;
};

typedef enum h_2e {h_2e_0 } h_2t;

// Special case. Anonymous BUT in translation unit scope
enum { h_0 };

// ~=~=
// Inline
// We Inline anonymous enum
// ~=~=
typedef enum {i_0} i_0t;
struct i_A_s {
  enum { i_1 } A_m;
};
void i_foo1( enum { i_2 });
void (*i_foo2)(enum { i_2 });
// Special case. Named Enum BUT as a function argument
void i_foo3( enum i_a { i_ae_0 });
void (*i_foo4)( enum i_a { i_ae_0 });

// Other Fun

struct S0 {
  enum B { B0 = 1, B1, B2 } * bar;
};

#define MAX_SIZE 100
union S1 {
  enum C { C0 = 1, C1 = 1, C2 = 2, C3 = 0x3, C4 = 1 << 2, C5 = C1 + C4, C6, C7 = MAX_SIZE + 1 } bar;
};

#define MAX_SIZE 101
enum D { D0 = MAX_SIZE  } ;
typedef enum F { F0 = 10 } F;
typedef struct G {
  F f;
} G;
