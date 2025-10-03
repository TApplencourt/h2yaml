enum A { A0 };
enum { A1 };

struct S0 {
  enum B { B0 = 1, B1, B2 } * bar;
};

union S1 {
  enum C { C0 = 1, C1 = 2, C2 = 0x3, C3 = C1 + C2 } bar;
};

typedef enum { D0 } D_t;
typedef enum E { E0 } E_t;

typedef enum F { F0 = 10 } F;
typedef struct G {
  F f;
} G;

struct S2 {
  enum { H0 } a;
};

void foo1(enum {H0});

void (*foo2)(enum {H0});
