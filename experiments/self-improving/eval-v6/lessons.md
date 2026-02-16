# Accumulated Lessons



### Epoch 0 Lessons
When modifying file discovery or filtering logic, verify that the filter only applies to the intended scope (e.g., user-specified targets) and not to the tool's own internal modules or initialization paths.

After making changes to a CLI tool, run a basic sanity check (like --version or --help) to verify the tool still initializes correctly before running the full test suite.

When distinguishing between 'missing/None' and 'empty' in conditionals, use explicit identity checks (`is None`) rather than truthiness checks (`not x`), since empty collections are falsy but semantically different from None.

When a fix involves recursive file traversal, consider all code paths that use that traversal - not just the one mentioned in the issue. Internal tool modules often share discovery mechanisms with user-facing features.

Before finalizing a patch, trace through what happens when the modified code path is called during tool startup, not just during the operation described in the issue.
