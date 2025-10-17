union A_t {
  int A0;
  float B0;
};
void foo(union A_t *bar);

union B_t {
  struct {
    int B0;
  } B_s;
};

union C {
  struct {
    union C *ptr;
  } C_s;
};
