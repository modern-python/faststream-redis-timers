# Glossary

The ubiquitous language of `faststream-redis-timers` — Redis-backed distributed
timer scheduling exposed as a FastStream broker. The domain terms code, specs,
and capability pages share. This is a glossary, not a spec: terms only, no
implementation detail.

**Timer**:
A scheduled future delivery — a message bound to a topic that becomes
deliverable at its activation time, identified by a timer id.
_Avoid_: job, task, alarm

**Topic**:
The named channel a timer is scheduled on and that a subscriber consumes from.
_Avoid_: queue, channel, stream

**TimerStore**:
The module that owns the timer lifecycle — scheduling, claiming, and removal —
across every topic, behind one interface.
_Avoid_: repository, backend, client

**Activation time**:
The moment a timer becomes due for delivery.
_Avoid_: deadline, fire time, TTL

**Schedule**:
To register a new timer to become due at its activation time.
_Avoid_: enqueue, publish, set

**Due**:
Describes a timer whose activation time has passed and which is therefore
eligible to be claimed.
_Avoid_: ready, expired, ripe

**Claim**:
To lease a due timer for processing, pushing its activation forward by the lease
so no other worker takes it concurrently.
_Avoid_: lock, acquire, reserve

**Lease**:
The temporary hold a worker has on a claimed timer; it expires after a fixed
duration, returning the timer to due if the worker has not committed it.
_Avoid_: lock, reservation

**Commit**:
To remove a timer permanently after a handler has processed it successfully.
_Avoid_: ack, complete, finish

**Cancel**:
To remove a still-pending timer before it fires.
_Avoid_: delete, abort, revoke

**Pending**:
Describes a timer that has been scheduled and neither committed nor cancelled;
includes timers currently leased.
_Avoid_: active, open, queued
