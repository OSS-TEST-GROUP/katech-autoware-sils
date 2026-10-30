// Linux-only isolated lifecycle workaround; does not suppress node destruction.
// The plugin's weak_ptr control-block vtables can outlive pluginlib's dlclose.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
void * dlopen(const char * filename,int flags)
{
  void * (*original)(const char *,int)=dlsym(RTLD_NEXT,"dlopen");
  if(!original) abort();
  const char * name=filename?strrchr(filename,'/'):NULL;
  name=name?name+1:filename;
  if(name && !strcmp(name,"libautoware_mission_planner_universe_lanelet2_plugins.so")) {
    flags|=RTLD_NODELETE;
    fprintf(stderr,"[KCITY_PLUGIN_LIFETIME] RTLD_NODELETE %s\n",filename);
  }
  return original(filename,flags);
}
