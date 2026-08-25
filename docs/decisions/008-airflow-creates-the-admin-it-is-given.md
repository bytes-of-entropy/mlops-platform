# 008: Airflow creates the admin account it is given, and its username is pinned

- **Date:** 2026-08-23
- **Status:** accepted
- **Component:** `compose/`
- **Milestone:** r3-m0

## Context

The spine documented an Airflow login assembled from two required variables, `AIRFLOW_ADMIN_USER`
and `AIRFLOW_ADMIN_PASSWORD`, passed to the container as `_AIRFLOW_WWW_USER_USERNAME` and
`_AIRFLOW_WWW_USER_PASSWORD`. Neither did anything.

The image's entrypoint acts on those two variables only when `_AIRFLOW_WWW_USER_CREATE` is set to a
non-empty value, and the file never set it. `command: standalone` then reaches
`create_admin_standalone()`, which looks for a user named exactly `admin`, and on not finding one
generates a sixteen-character random password, writes it to
`$AIRFLOW_HOME/standalone_admin_password.txt` inside the container, and prints it to the log. So the
account a reader was told to log in with did not exist, and the account that did exist had a password
recoverable only from `docker compose logs airflow`.

What makes this worth a record is that the two checks nearest to it both passed. `.env.example`
declared the variable and the compose file interpolated it, which is the whole of what either
direction of the existing parity rule asserts. Being read by the file is not the same as being acted
on by the image, and nothing in the repository was looking one level deeper than that.

## Decision

Set `_AIRFLOW_DB_MIGRATE` and `_AIRFLOW_WWW_USER_CREATE`, so the entrypoint migrates the schema and
then creates the account it was handed. Migration is not incidental: creating a user needs a schema,
and the entrypoint tolerates its own failure, so an unmigrated database turns the create into a
no-op and hands the password back to standalone: the original bug, one step further along.

Pin `_AIRFLOW_WWW_USER_USERNAME` to `admin` in the compose file and drop `AIRFLOW_ADMIN_USER` from
`.env.example`, leaving seven required variables. Standalone keys on that exact name, so any other
value leaves a second Admin-role account whose password lives in a file inside the container. A
variable whose only correct value is one specific string is not a variable, and pretending otherwise
is what produced this defect in the first place.

Generalise the class rather than the instance: a credential handed to an image must come with
whatever flag makes that image act on it, asserted for every service by
`test_a_credential_the_image_was_never_told_to_use_is_not_configuration`.

## Alternative rejected

Drop `command: standalone` and run `airflow webserver` beside a separate scheduler service, letting
the entrypoint own migration and user creation the way a real deployment does. It is the more
faithful Airflow and it keeps a configurable username. It loses on the envelope decided in `003`: a
second container's memory, permanently, bought with a username nobody needs to choose. If a later
milestone needs more than one Airflow account, this is the decision to revisit, not extend.

The weaker alternative was to keep standalone and document that the password comes from the
container log. Honest, and cheaper than either fix, but it replaces a credential the operator sets
with one they have to go and find, and it leaves two variables in `.env.example` that do nothing.

## Prediction (recorded before the evidence)

I expect the new rule to catch at least one more instance by M2, most likely in a chart's values or
an image's own entrypoint, because the shape (a value passed to software that has to be told
separately to read it) is common and invisible. I expect the pinned username to be questioned by
anyone reading the file and to survive the question.

## Deciding evidence

None from a running stack: this machine has no container runtime. The mechanism comes from the
image's entrypoint documentation and from the 2.9.2 source of `create_admin_standalone`, which reads
`find_user("admin")` and writes the generated password under `AIRFLOW_HOME`. The compose-side rule
was verified by deleting `_AIRFLOW_WWW_USER_CREATE` and confirming the failure names the service,
the variable and the missing flag. The first successful login on the build machine is the
outstanding confirmation, and until it happens this record's claim is about the mechanism rather
than about the stack.

## What would change my mind

An Airflow release in which standalone honours the entrypoint's username instead of looking for
`admin`, or a milestone needing a second account. Either makes webserver-plus-scheduler the cheaper
shape and this record superseded rather than amended.

## Consequences

Easy: a login that is the same on every machine, derived from a credential the operator generated.
One fewer required variable. A rule that fails in the contract tier, with no runtime, for a class of
defect that previously needed a running Airflow and someone trying to log into it.

Hard: exactly one Airflow account, by construction. The contract suite goes from 66 tests to 68.
