#include <dlfcn.h>
#include <cfenv>
#include <cstdio>
int main() {
  feenableexcept(FE_INVALID|FE_DIVBYZERO);
  void *lib=dlopen("/work/local_plugin.so",RTLD_NOW|RTLD_LOCAL);if(!lib){puts(dlerror());return 1;}
  auto probe=reinterpret_cast<bool(*)(bool)>(dlsym(lib,"probe"));if(!probe)return 2;
  if(!probe(false)||probe(true))return 3;
  puts("PASS: RTLD_LOCAL component normal input forwarded; invalid domain rejected; traps enabled");
}
