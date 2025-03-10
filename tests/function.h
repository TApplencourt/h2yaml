#include <stddef.h>
void f0(int);
void f1(int b);
void f2(void);

struct a {
  int i;
};
struct a f3(const struct a x[]);

typedef int (*a_t)(int);
typedef int (*b_t)(void);

int f4(int a[]);
int f5(const int *a);

typedef int c_t;
typedef c_t (*d_t)(int x);

void f6(int, ...);

typedef void(e_t)(int, ...);

void f7();

__attribute__((deprecated("foo"))) size_t f8(size_t size
                                             __attribute__((unused)));

static inline void f9(void);

void f10(void) {}
