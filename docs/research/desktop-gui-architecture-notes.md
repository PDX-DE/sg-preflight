# Desktop GUI Architecture Notes

This is a research note for the future desktop operator shell.

## Current product shape

`sg-preflight` is currently strongest as:

- Python core engine
- CLI over the same engine
- local web UI over the same engine

That is the shipping product surface today.

## Future direction

The future richer operator shell should be:

```text
Python core engine
  -> CLI
  -> local web UI
  -> desktop GUI wrapper
```

## Rules

- Do not replace the Python core.
- Do not fork the validation logic into a second engine.
- The desktop GUI should call into the same core services/actions/evidence model.
- The browser UI stays useful even after a desktop shell exists.

## Why a desktop shell is justified later

A browser-only surface becomes limiting once the workflow leans harder on:

- Blender / RaCo / RaCoHeadless orchestration
- local file opening and subprocess-heavy flows
- screenshot and image-evidence capture
- filesystem-heavy checker execution
- Excel/report packaging
- BMW-side scripts once access exists

At that point, a desktop wrapper becomes the better operator shell.

## What should not change

- one validation core
- one action system
- one evidence model
- one result / handoff flow
- one source-of-truth story around mirrored SG checkers and external BMW blockers
