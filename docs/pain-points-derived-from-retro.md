# Pain points derived from SG retro notes

These are the highest-value signals for a first PoC because they appear repeatedly in the retrospective notes and map to deterministic checks:

- Too many obvious findings during internal rack sessions
- Need an actual 3D Car integration strategy, especially about testing
- Some procedures are confusing and not documented
- Ticket definition, order, and dependencies should be documented better
- Finding car-specific configurations is hard because there is no central authority
- Unity / CarLib integration is described as a black box and hard to debug
- Multiple parts need to be built and moved manually, making diagnosis harder

Not every pain can be solved by validation tooling alone.

This PoC focuses on the subset that can be converted into:
- earlier deterministic failure
- reusable evidence
- less ambiguous debugging
- less repeated manual checking
