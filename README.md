# ArtAgents

ArtAgents is a harness for helping you use agents to make art and creative work.

## How it works (for humans)

Executors perform one concrete piece of work. Orchestrators combine executors into workflows. Elements are reusable render pieces (effects, animations, transitions) used by both. Everything is invoked through a single gateway: `python3 -m artagents`.

![ArtAgents architecture: orchestrators route work to executors and render elements](docs/assets/artagents-orchestration.png)

## How it works (for agents)

Give this to your agents to get started:

<div align="center">

```text
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                            ┃
┃   ╲╱╲╱╲╱╲╱╳────────────────────────────────────────────────────╳╲╱╲╱╲╱╲╱   ┃
┃   ╱╲╱╲╱╲╱╲╳────────────────────────────────────────────────────╳╱╲╱╲╱╲╱╲   ┃
┃                                                                            ┃
┃                    T H E   A R T A G E N T S   R I T E                     ┃
┃                                                                            ┃
┃                      ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·                       ┃
┃                                                                            ┃
┃                   ──  ◇  W H A T   T H I S   I S  ◇  ──                    ┃
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
┃                                                                            ┃
┃                    ──  ◇  U S I N G   T O O L S  ◇  ──                     ┃
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
┃               ──  ◇  F O R G E   A   N E W   T O O L  ◇  ──                ┃
┃                                                                            ┃
┃     ·  copy from   docs/templates/[executor|orchestrator|element]/  ·      ┃
┃     ·  then read   docs/creating-tools.md                           ·      ┃
┃                                                                            ┃
┃                      ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·                       ┃
┃                                                                            ┃
┃                    ·  generated files live in  runs/  ·                    ┃
┃                                                                            ┃
┃   ╲╱╲╱╲╱╲╱╳────────────────────────────────────────────────────╳╲╱╲╱╲╱╲╱   ┃
┃   ╱╲╱╲╱╲╱╲╳────────────────────────────────────────────────────╳╱╲╱╲╱╲╱╲   ┃
┃                                                                            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

</div>

## License

Open Source Native License (OSNL) v0.2 — see [`LICENSE`](LICENSE).
