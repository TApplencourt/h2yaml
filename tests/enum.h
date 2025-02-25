enum A { A0 };

struct S0 {
  enum B { B0 = 1 } * bar;
};

union S1 {
  enum C { C0 = 1, C1 = 2 } * bar;
};

typedef enum { D0 } D_t;
typedef enum E { E0 } E_t;

typedef enum F { F0 = 10 } F;
typedef struct G {
  F f;
} G;
