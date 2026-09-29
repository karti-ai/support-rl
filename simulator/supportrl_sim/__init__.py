"""Customer simulators.

Two modes:

* **scripted** (:mod:`supportrl_sim.scripted`): deterministic replay of an episode's written
  customer turns. The customer never reacts to the model, so eval is reproducible and
  training rewards are comparable across rollouts. This is what ``baseline``, ``eval``, the
  verifiers environment and both training backends use.
* **LLM customer** (:mod:`supportrl_sim.llm`): an OpenAI-compatible model plays the customer
  from a persona and a goal. Use it to *generate new candidate episodes* (they come out
  unlabelled and marked ``unreviewed``; every loader skips them until a human writes the
  labels) and to *play-test* a model interactively. It is never in the reward path.
"""
