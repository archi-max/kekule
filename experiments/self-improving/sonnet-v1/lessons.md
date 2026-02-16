# Accumulated Lessons



### Epoch 0 Lessons
## Test Execution Before Submission
- Always verify that target tests can actually RUN before claiming a fix works. If tests fail to execute due to import errors, missing modules, or fixture failures, resolve these blockers first. A patch that passes static analysis but fails at test runtime is not complete.

## Correct Modification Location
- Trace the execution path from user input to buggy behavior before modifying code. When an issue mentions a CLI flag (e.g., --recursive), find where that flag is both parsed AND applied. The fix often belongs in a different module than where symptoms appear.
- When modifying file enumeration or discovery logic, test with both package directories (containing __init__.py) and non-package directories. Different code paths often handle these cases differently.

## Avoid Replacing Library Functions
- Prefer minimal targeted fixes over replacing standard library functions or well-tested utility functions with custom implementations. Custom replacements often have subtle semantic differences that cause widespread regressions.

## Boolean and Collection Edge Cases
- Distinguish between None (missing), empty collection [], and non-empty collection. Use explicit `is None` or `len(x) == 0` checks rather than `if not x:` when the semantic difference matters.
- When filtering collections or paths, test both positive matches (should be filtered) AND negative matches (should pass through) to catch over-aggressive filtering.

## Test Environment Validation
- If multiple tests fail with identical errors (e.g., same import error or unknown symbol error), check whether this indicates an environment/dependency issue rather than a patch problem. Address environment issues before debugging patch logic.
