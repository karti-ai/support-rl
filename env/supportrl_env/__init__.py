"""verifiers environment for any support-rl project.

    from supportrl_env import load_environment
    env = load_environment(project="examples/zoomberg", split="train")

For hosted training the environment must be self-contained, so ``supportrl env build``
writes a package that bundles the scorer and your project files (see env/README.md).
"""

from .environment import load_environment

__all__ = ["load_environment"]
