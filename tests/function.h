void f0(int);
void f1(int b);
void f2(void);

struct a {
  int i;
};
struct a f3(const struct a x);

typedef int (*a_t)(int);
int f4(int a[]);
int f5(const int *a);

typedef int b_t;
typedef b_t (*c_t)(int x);

void f6(int, ...);

typedef void(d_t)(int, ...);
