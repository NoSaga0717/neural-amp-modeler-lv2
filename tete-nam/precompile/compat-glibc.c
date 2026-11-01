/* Compatibilité glibc < 2.38 (Raspberry Pi OS Bookworm) : libstdc++ statique
   appelle les variantes C23 de strtol ; on les redirige vers les classiques. */
#include <stdlib.h>
__attribute__((visibility("hidden"))) long __isoc23_strtol(const char *s, char **e, int b) { return strtol(s, e, b); }
__attribute__((visibility("hidden"))) long long __isoc23_strtoll(const char *s, char **e, int b) { return strtoll(s, e, b); }
__attribute__((visibility("hidden"))) unsigned long __isoc23_strtoul(const char *s, char **e, int b) { return strtoul(s, e, b); }
__attribute__((visibility("hidden"))) unsigned long long __isoc23_strtoull(const char *s, char **e, int b) { return strtoull(s, e, b); }
