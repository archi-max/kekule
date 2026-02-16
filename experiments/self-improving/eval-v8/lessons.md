# Accumulated Lessons



### Epoch 0 Lessons
## Runtime Validation
- Before submitting any patch, always run a minimal reproduction script or targeted test to verify the fix actually works. Static code analysis alone is insufficient - many fixes look correct but fail at runtime due to edge cases or integration issues.
- If the target test fails to even run (import errors, missing modules, fixture setup failures), treat this as a blocking issue that must be resolved before claiming the fix works.

## Correct File Identification
- When a bug involves multiple code paths (e.g., single files vs. directories, recursive vs. non-recursive modes), trace ALL code paths that the issue describes, not just the most obvious one. The fix often needs to be in a different module than where symptoms appear.
- Read the issue description carefully for hints about which module or function needs modification. If the issue mentions a specific config option or CLI flag, grep for where that option is parsed AND where it is applied.

## Regression Prevention
- When adding conditional checks (e.g., filtering files), ensure the check doesn't accidentally block valid inputs. Test with both matching and non-matching cases.
- If a test suite shows many failures with the same error message (e.g., UnknownMessageError for a specific symbol), investigate whether this is an environment/dependency issue rather than a patch problem.

## Boolean Edge Cases
- When fixing code that checks truthiness of collections, distinguish between `None` (missing), empty collection `[]`, and non-empty collection. Python treats both `None` and `[]` as falsy, so `if not x:` conflates them - use explicit `is None` checks when the difference matters.

### Epoch 1 Lessons
## Test Environment Verification
- Before submitting a patch, verify that the target test can actually execute (not just ERROR during setup). If a test ERRORs due to missing dependencies, fixture failures, or import errors, this is a blocking issue - the fix cannot be validated.
- When running a test file shows widespread failures with the same error message across many tests, investigate whether this is caused by an environment or infrastructure issue rather than the patch itself.

## Regression Detection
- After applying a patch, run a broader set of tests from the same test file or module, not just the target test. If the fix causes regressions in unrelated tests, the approach needs reconsideration.
- When modifying code that is part of a larger pipeline (e.g., file discovery, initialization sequences), trace all callers of the modified code to ensure the change doesn't break other features.

## Incremental Verification
- For fixes involving conditional logic changes (like changing `if not x` to `if x is None`), create a minimal test case that can run in isolation first, before running the full test suite. This isolates whether the logic is correct from whether the test infrastructure works.
