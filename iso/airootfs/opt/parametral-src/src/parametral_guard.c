/*
 * Parametral seccomp_guard — syscall filter + rlimit applier + exec wrapper.
 *
 * Why this exists: bubblewrap 0.13's --seccomp fd contract could not be
 * validated on this kernel (the arch check misbehaved, producing SIGSYS on a
 * known-good filter). Rather than ship an unverified assumption, the sandbox
 * runs this guard as PID 1 inside the namespaces; the filter is compiled here,
 * where the offsets are exercised by tests/test_sandbox_isolation.py.
 *
 * Behaviour: blocked syscalls return EPERM (graceful degradation) instead of
 * killing the process, so ordinary tools (apt, python, node) keep working.
 * no_new_privs is set before the filter, and the filter is irreversible.
 */
#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>

#define EPERM_RET (SECCOMP_RET_ERRNO | (EPERM & SECCOMP_RET_DATA))

/* Two BPF instructions: "if nr == X, return EPERM". */
#define DENY_NR(nr)                                                     \
    BPF_JUMP (BPF_JMP | BPF_JEQ | BPF_K, (nr), 0, 1),                   \
    BPF_STMT (BPF_RET | BPF_K, EPERM_RET)

static struct sock_filter filter[] = {
    /* Refuse anything that is not the native x86_64 ABI. */
    BPF_STMT (BPF_LD | BPF_W | BPF_ABS, offsetof (struct seccomp_data, arch)),
    BPF_JUMP (BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
    BPF_STMT (BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),

    BPF_STMT (BPF_LD | BPF_W | BPF_ABS, offsetof (struct seccomp_data, nr)),

    /* x32 ABI shares the syscall table with a flag bit: block the whole range. */
    BPF_JUMP (BPF_JMP | BPF_JGE | BPF_K, 0x40000000, 0, 1),
    BPF_STMT (BPF_RET | BPF_K, EPERM_RET),

#ifdef __NR_mount
    DENY_NR (__NR_mount),
#endif
#ifdef __NR_umount2
    DENY_NR (__NR_umount2),
#endif
#ifdef __NR_pivot_root
    DENY_NR (__NR_pivot_root),
#endif
#ifdef __NR_chroot
    DENY_NR (__NR_chroot),
#endif
#ifdef __NR_ptrace
    DENY_NR (__NR_ptrace),
#endif
#ifdef __NR_process_vm_readv
    DENY_NR (__NR_process_vm_readv),
    DENY_NR (__NR_process_vm_writev),
#endif
#ifdef __NR_kexec_load
    DENY_NR (__NR_kexec_load),
#endif
#ifdef __NR_kexec_file_load
    DENY_NR (__NR_kexec_file_load),
#endif
#ifdef __NR_bpf
    DENY_NR (__NR_bpf),
#endif
#ifdef __NR_perf_event_open
    DENY_NR (__NR_perf_event_open),
#endif
#ifdef __NR_setns
    DENY_NR (__NR_setns),
#endif
#ifdef __NR_unshare
    DENY_NR (__NR_unshare),
#endif
#ifdef __NR_init_module
    DENY_NR (__NR_init_module),
#endif
#ifdef __NR_finit_module
    DENY_NR (__NR_finit_module),
#endif
#ifdef __NR_delete_module
    DENY_NR (__NR_delete_module),
#endif
#ifdef __NR_swapon
    DENY_NR (__NR_swapon),
    DENY_NR (__NR_swapoff),
#endif
#ifdef __NR_reboot
    DENY_NR (__NR_reboot),
#endif
#ifdef __NR_iopl
    DENY_NR (__NR_iopl),
    DENY_NR (__NR_ioperm),
#endif
#ifdef __NR_acct
    DENY_NR (__NR_acct),
#endif
#ifdef __NR_add_key
    DENY_NR (__NR_add_key),
    DENY_NR (__NR_request_key),
#endif
#ifdef __NR_keyctl
    DENY_NR (__NR_keyctl),
#endif
#ifdef __NR_userfaultfd
    DENY_NR (__NR_userfaultfd),
#endif
#ifdef __NR_open_tree
    DENY_NR (__NR_open_tree),
    DENY_NR (__NR_move_mount),
#endif
#ifdef __NR_fsopen
    DENY_NR (__NR_fsopen),
    DENY_NR (__NR_fsconfig),
    DENY_NR (__NR_fsmount),
    DENY_NR (__NR_fspick),
#endif
#ifdef __NR_mount_setattr
    DENY_NR (__NR_mount_setattr),
#endif
#ifdef __NR_pidfd_getfd
    DENY_NR (__NR_pidfd_getfd),
#endif
#ifdef __NR_kcmp
    DENY_NR (__NR_kcmp),
#endif
#ifdef __NR_name_to_handle_at
    DENY_NR (__NR_name_to_handle_at),
    DENY_NR (__NR_open_by_handle_at),
#endif

    BPF_STMT (BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
};

static int
apply_rlimit (int resource, const char *env_name)
{
  const char *raw = getenv (env_name);
  if (raw == NULL || *raw == '\0')
    return 0;

  char *end = NULL;
  unsigned long long value = strtoull (raw, &end, 10);
  if (end == NULL || *end != '\0')
    {
      fprintf (stderr, "seccomp_guard: bad %s=%s\n", env_name, raw);
      return -1;
    }

  struct rlimit limit;
  limit.rlim_cur = (rlim_t) value;
  limit.rlim_max = (rlim_t) value;
  if (setrlimit (resource, &limit) != 0)
    {
      fprintf (stderr, "seccomp_guard: setrlimit(%d) failed: %s\n", resource, strerror (errno));
      return -1;
    }
  return 0;
}

int
main (int argc, char **argv)
{
  if (argc < 2)
    {
      fprintf (stderr, "usage: seccomp_guard <command> [args...]\n");
      return 127;
    }

  /* Limits first: they must be in force before the target runs. */
  if (apply_rlimit (RLIMIT_AS, "PARAMETRAL_RLIMIT_AS_BYTES") != 0 ||
      apply_rlimit (RLIMIT_CPU, "PARAMETRAL_RLIMIT_CPU_SECONDS") != 0 ||
      apply_rlimit (RLIMIT_FSIZE, "PARAMETRAL_RLIMIT_FSIZE_BYTES") != 0)
    return 126;

  struct rlimit no_core = { 0, 0 };
  if (setrlimit (RLIMIT_CORE, &no_core) != 0)
    {
      fprintf (stderr, "seccomp_guard: cannot disable core dumps: %s\n", strerror (errno));
      return 126;
    }

  struct sock_fprog program = {
    .len = (unsigned short) (sizeof (filter) / sizeof (filter[0])),
    .filter = filter,
  };

  if (prctl (PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0)
    {
      fprintf (stderr, "seccomp_guard: PR_SET_NO_NEW_PRIVS failed: %s\n", strerror (errno));
      return 126;
    }
  if (syscall (SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &program) != 0)
    {
      fprintf (stderr, "seccomp_guard: seccomp(SET_MODE_FILTER) failed: %s\n", strerror (errno));
      return 126;
    }

  execvp (argv[1], &argv[1]);
  fprintf (stderr, "seccomp_guard: exec %s failed: %s\n", argv[1], strerror (errno));
  return 127;
}
