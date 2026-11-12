// Harness.Assets.BatchExit - safe exit for the *Batch entry points of this skill (Unity 6000.3).
// Same pattern as headless-ops' HarnessCli.Exit, copied so asset-pipeline stays self-contained.
// ⚠ version-sensitive: on 6000.3.21f1 a synchronous EditorApplication.Exit inside -executeMethod at startup crashed once
// during domain unload (exit 134). So:
//   - run WITHOUT -quit (headless-ops: `unity.sh exec <Method> --no-quit`): the exit is deferred one editor tick and the code
//     is kept in SessionState, so it survives a domain reload. Exit codes 0/1/2 reach the shell unchanged.
//   - run WITH -quit: no EditorApplication.Exit at all; code 0 returns (Unity quits with 0), non-zero throws (Unity exits 1).
//   - interactive editor (menu, MCP execute_code): logs only, never quits the editor.
using System;
using UnityEditor;
using UnityEngine;

namespace Harness.Assets
{
    public static class BatchExit
    {
        const string PendingKey = "Harness.Assets.PendingExit";

        public static void Exit(int code)
        {
            if (!Application.isBatchMode) return;
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-quit") >= 0)
            {
                if (code != 0) throw new Exception("Harness.Assets batch step failed with code " + code);
                return;
            }
            SessionState.SetInt(PendingKey, code + 1);
            EditorApplication.delayCall += () => EditorApplication.Exit(code);
        }

        [InitializeOnLoadMethod]
        static void ExitAfterReload()
        {
            if (!Application.isBatchMode) return;
            int pending = SessionState.GetInt(PendingKey, 0);
            if (pending == 0) return;
            SessionState.EraseInt(PendingKey);
            EditorApplication.delayCall += () => EditorApplication.Exit(pending - 1);
        }
    }
}
