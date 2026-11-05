/* The executable of a minimal `.app`: launchd gives an app `/` as its working directory, and
 * MAME writes `error.log` and `debug.log` beside the one it runs in, so this changes into the
 * run's own (the server passes it as `SCRY_APP_CWD`) and execs the emulator beside it. `exec`
 * keeps the pid, which is the one the server finds by the session's own token. */
#include <mach-o/dyld.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef SCRY_APP_EXEC
#error "compile with -DSCRY_APP_EXEC=<the emulator beside this launcher>"
#endif

int main(int argc, char **argv)
{
    const char *cwd = getenv("SCRY_APP_CWD");
    if (cwd != NULL && *cwd != '\0' && chdir(cwd) != 0)
        return 126;

    char self[4096];
    uint32_t size = sizeof self;
    if (_NSGetExecutablePath(self, &size) != 0)
        return 127;
    char *slash = strrchr(self, '/');
    if (slash == NULL)
        return 127;
    strcpy(slash + 1, SCRY_APP_EXEC);

    char **args = calloc((size_t)argc + 1, sizeof *args);   /* execv needs its NULL */
    if (args == NULL)
        return 127;
    args[0] = self;
    for (int i = 1; i < argc; i++)
        args[i] = argv[i];
    execv(self, args);
    return 127;
}
