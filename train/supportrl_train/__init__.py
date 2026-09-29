"""Training backends.

* :mod:`supportrl_train.prime` -- hosted LoRA RL on Prime Intellect: builds the environment
  package, renders a run config from a template and prints (or runs) the two commands.
* :mod:`supportrl_train.trl_grpo` -- self-hosted GRPO + LoRA with TRL on one GPU.
* :mod:`supportrl_train.select` -- checkpoint selection on the project's selection subset
  (``dev_val``) with the frozen inference settings. The rule is declared in supportrl.yaml
  before training: highest composite, ties to the later step.
"""
