struct A0 { int x; };
struct A1 { int x; } a;
struct A2 { struct { int x; } a; };
struct A3 { struct { int x; }; };
struct A4 { struct B1 { int x; } a4; };
typedef struct A5 { struct B5 { int x; } b; } a5;
struct A6 { union { struct B6 { int x; } b; } a6; };
