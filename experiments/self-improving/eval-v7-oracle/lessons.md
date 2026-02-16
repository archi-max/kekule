# Accumulated Lessons



### Epoch 0 Lessons
When modifying a method that has both __repr__ and __str__ implementations, check the test to understand whether they should return the same output or different outputs. If a test asserts equality between str() and repr(), ensure your __str__ implementation returns the same format as __repr__.

When a fix involves changing conditional logic (like 'if not x' to 'if x is None'), trace through ALL code paths affected by the change, not just the target behavior. Check how downstream code depends on return values.

Before submitting a patch, run the full test suite for the affected module, not just the target test. Patches that fix the target test but break dozens of other tests are not acceptable.

When fixing behavior for edge cases (empty collections, None values, zero-length inputs), ensure the fix handles all three distinct cases: undefined/None, empty, and populated. Each may require different behavior.

If tests fail during setup (import errors, missing modules), verify that your fix doesn't inadvertently change imports or module structure. Check that all test dependencies remain satisfied.
