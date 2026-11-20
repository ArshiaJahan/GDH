Tune the prompt improver against a real model

Live eval on Claude Haiku 5.5 (48 prompts): vague ask-rate 0.62 -> 0.83,
clear false-asks 0.08 -> 0.04.

- Add decision rules: ask on subjective success, open variants and
  unreproduced bugs; never assume what the user wants to define done
- ASK replies may omit the task card; it is synthesized after the answers
- Parser accepts object cited facts and drops invented-topic questions
- Raise the output cap to 2048 tokens; template version pi-eval-2
- Eval resets the circuit breaker per prompt; record measured results
