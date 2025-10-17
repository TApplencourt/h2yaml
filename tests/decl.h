#include <stddef.h>
#include <stdint.h>

int a0 = 1;
uint64_t a1 = 2;
size_t a2 = 3;

char *a3 = NULL;
int **a4;
long ***a5;

void (*a6)(double, int);
void (*a7)(double a, int);

typedef int a8_t;
a8_t (*a8)(a8_t);

const int a9[];
const int a9_init[] = {};

const int a10[];
const int a10[25];

volatile const int a11;

const int *const restrict a12;

extern const char *a13;

int a14[][3];

static int a = 4;
