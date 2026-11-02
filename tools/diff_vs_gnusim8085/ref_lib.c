/* Thin C API around the ORIGINAL GNUSim8085 core so Python can use it as a test oracle. */
#include <string.h>
#include "8085.h"
void ref_reset(void){ eef_reset_all(); }
void ref_set(const int *v){
  sys.reg.a=v[0]; sys.reg.b=v[1]; sys.reg.c=v[2]; sys.reg.d=v[3]; sys.reg.e=v[4];
  sys.reg.h=v[5]; sys.reg.l=v[6];
  eef_regpair_put('S', v[7]);
  sys.flag.s=v[8]; sys.flag.z=v[9]; sys.flag.ac=v[10]; sys.flag.p=v[11]; sys.flag.c=v[12];
}
void ref_load(int addr, const unsigned char *buf, int n){ memcpy(&sys.mem[addr], buf, n); }
void ref_dump(int addr, unsigned char *buf, int n){ memcpy(buf, &sys.mem[addr], n); }
void ref_load_io(const unsigned char *buf){ memcpy(sys.io, buf, 256); }
void ref_dump_io(unsigned char *buf){ memcpy(buf, sys.io, 256); }
void ref_run(int addr){ eef_execute_from(addr, NULL, 0); }
void ref_get(int *o){
  o[0]=sys.reg.a; o[1]=sys.reg.b; o[2]=sys.reg.c; o[3]=sys.reg.d; o[4]=sys.reg.e;
  o[5]=sys.reg.h; o[6]=sys.reg.l; o[7]=eef_regpair_get('S');
  o[8]=sys.flag.s; o[9]=sys.flag.z; o[10]=sys.flag.ac; o[11]=sys.flag.p; o[12]=sys.flag.c;
  o[13]=eef_pc_get();
}
