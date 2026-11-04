# Use case

Several institutions each hold data that must not leave them. A researcher wants a model trained on all of it.

**Who acts:**

- **A researcher**, who has a training procedure and a question. They don't administer any of the institutions' systems.
- **Each institution**, which holds its data, decides what runs on its systems and what leaves them. It wants the procedure to be something its usual compute service can run, without standing up and looking after a new system for each collaboration.
- **A cloud operator or coordinator**, who connects the institutions' services and knows what's available where.

**What happens:**

1. The researcher names the training procedure and the institutions that should take part, through the same interface they use for other analyses.
2. Each institution runs the procedure on its own data, on its own compute, under its own rules.
3. The institutions' intermediate results are combined, round by round, without anyone seeing another institution's data.
4. The researcher gets the final model and a record of what ran where.

**Why:** moving data is often not allowed, and pooling it is often not wanted. Sharing compute services across institutions is already happening for other analyses, so researchers shouldn't have to learn a second way to run things, and institutions shouldn't have to operate a second platform for it.
