# ArtAgents

ArtAgents is a harness for helping you use agents to make art and creative work.

## How it works

Give this to your agents to get started:

<div align="center">

```text
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━◇━━━━━━━━━━━━━━◇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                            ┃
┃   ╲╱╲╱╲╱╲╱╳────────────────────────────────────────────────────╳╲╱╲╱╲╱╲╱   ┃
┃                        ═══  A R T A G E N T S  ═══                         ┃
┃   ╱╲╱╲╱╲╱╲╳────────────────────────────────────────────────────╳╱╲╱╲╱╲╱╲   ┃
┃                                                                            ┃
┃                         ──  ◇  What This Is  ◇  ──                         ┃
┃                                                                            ┃
┃             ·  a file-based toolkit for agents to help them  ·             ┃
┃             ·  make art and creative work alongside a human  ·             ┃
┃                                                                            ┃
┃                   ·  three kinds of beings live here:  ·                   ┃
┃                                                                            ┃
┃          ·  EXECUTORS      perform one piece of work            ·          ┃
┃          ·  ORCHESTRATORS  combine executors together           ·          ┃
┃          ·  ELEMENTS       reusable render pieces used by both  ·          ┃
┃                                                                            ┃
┃    ·  every summons passes through one gate:   python3 -m artagents  ·     ┃
┃                                                                            ┃
┃                      ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·                       ┃
◇                                                                            ◇
┃                         ──  ◇  Using Tools  ◇  ──                          ┃
┃                                                                            ┃
┃                              ·  find an id  ·                              ┃
┃     ·  python3 -m artagents [executors|orchestrators|elements] list  ·     ┃
┃                                                                            ┃
┃            ·  inspect to see inputs, outputs, how to invoke  ·             ┃
┃ ·  python3 -m artagents [executors|orchestrators|elements] inspect <id>  · ┃
┃                                                                            ┃
┃                                ·  run it  ·                                ┃
┃  ·  python3 -m artagents [executors|orchestrators] run <id> -- <args>  ·   ┃
┃                                                                            ┃
┃                      ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·                       ┃
┃                                                                            ┃
┃                      ──  ◇  Make Something New  ◇  ──                      ┃
┃                                                                            ┃
┃             ·  to create a new executor (a piece of work):  ·              ┃
┃                       copy  docs/templates/executor/                       ┃
◇                                                                            ◇
┃         ·  to combine executors in a new way (an orchestrator):  ·         ┃
┃                     copy  docs/templates/orchestrator/                     ┃
┃                                                                            ┃
┃           ·  new render piece? copy  docs/templates/element/  ·            ┃
┃                                                                            ┃
┃                  ·  then read  docs/creating-tools.md  ·                   ┃
┃                                                                            ┃
┃                      ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·                       ┃
┃                                                                            ┃
┃                            ──  ◇  Begin  ◇  ──                             ┃
┃                                                                            ┃
┃            ·  ask the maker what they want to make or learn  ·             ┃
┃                ·  if they want ideas, see  docs/ideas.md  ·                ┃
┃                    ·  generated files live in  runs/  ·                    ┃
┃                                                                            ┃
┃   ╲╱╲╱╲╱╲╱╳────────────────────────────────────────────────────╳╲╱╲╱╲╱╲╱   ┃
┃             ·  LEAVE THE WOODPILE HIGHER THAN YOU FOUND IT  ·              ┃
┃   ╱╲╱╲╱╲╱╲╳────────────────────────────────────────────────────╳╱╲╱╲╱╲╱╲   ┃
┃                                                                            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━◇━━━━━━━━━━━━━━◇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

</div>

## License

Open Source Native License (OSNL) v0.2 — see [`LICENSE`](LICENSE).
