/* Utility functions. */
#include <stdio.h>
#include "util.h"

#define MAX_LEN 64
#define SQUARE(x) ((x) * (x))

static int counter = 0;
const char *greeting = "hello { world";

typedef struct {
    int x, y;
} Point;

struct Node {
    struct Node *next;
    int value;
};

enum Color { RED, GREEN = 2, BLUE };

/* Adds two ints. */
int add(int a, int b) {
#if defined(FAST)
    if (a) {
#else
    if (a && b) {
#endif
        return a + b;
    }
    return 0;
}

static void helper(void) {
    char c = '{';
    printf("%c}", c);
}

#ifdef WIN32
void platform_init(void) { }
#else
void platform_init(void) { }
void posix_only(int flags);
#endif

struct Node *make_node(int v)
{
    return 0;
}
