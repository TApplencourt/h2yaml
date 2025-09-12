#include "struct_forward.h"

struct A0 {
  int x;
};

volatile struct A0 A0_v;

struct A1 {
  int x;
} a1;

struct A2 {
  struct {
    int x;
  } b2;
};

struct A3 {
  struct {
    int x;
  };
};

struct A4 {
  struct B4 {
    int x;
  } b4;
};

struct A5 {
  union {
    struct B5 {
      int x;
    } b5;
  } u;
};

struct A6 {
  unsigned x1 : 5;
  unsigned : 0;
  unsigned x2 : 6;
  unsigned x3 : 15;
};

// Typedef

typedef struct {
  int x;
} A7_t;

typedef struct A8 {
  int x;
} *A8_0_t, A8_1_t;

typedef struct A9 {
  struct B9 {
    int x;
  } b9;
} A9_t;

// Forward  Declaration
struct A10;
struct A10 {
  int x;
};

typedef struct A11 A11_t;
typedef struct A11 {
  int x;
} A11_t;

// Including Forward Declaration header
struct A12 {
  int a;
};

typedef struct A13 {
  int x;
} A13_t;

// Recursive
struct A14 {
  struct A14 *next;
};
