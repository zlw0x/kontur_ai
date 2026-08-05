"""One place that answers "where is this order", in one vocabulary.

What stood here was three lines inside `get_drawing_job`:

    status = ("READY" if has_model
              else "WAITING_FOR_USER_ANSWERS" if questions
              else job.status.value)

The first two are `OrderStatus`. The third is `JobStatus` — `PENDING`, `LEASED`,
`PAUSED`, `FAILED` — so the customer's status arrived in two vocabularies at once,
chosen by which branch happened to fire. The web page's `statusCopy` covers both
because it has had to.

Progress is not stored. It is read off the job on the way out, because the job is
where it already lives: the lease, the attempt count, the failure code and the
`retry_after` are all columns on `jobs`, kept current by the worker protocol and the
reaper. Copying them onto the order would be a second place for one truth to live,
and the second place is always the one that goes stale.

What *is* stored is what nobody can derive: the statuses somebody decided.
"""

from __future__ import annotations

from app.contracts import JobStatus, JobType, OrderStatus
from app.orders.state_machine import is_decided

#: What a leased job means for the order, by what the worker was asked to do. A
#: `LEASED` job says a worker holds it and says nothing about which stage that is;
#: the job's type does, and it is the only thing that does.
_LEASED_MEANS = {
    JobType.ANALYZE_DRAWING: OrderStatus.DRAWING_ANALYSIS,
    JobType.COMPILE_CAD_IR: OrderStatus.DRAWING_ANALYSIS,
    JobType.BUILD_CAD: OrderStatus.CAD_BUILDING,
    JobType.VALIDATE_CAD: OrderStatus.CAD_VALIDATION,
}

_STOPPED = {
    JobStatus.FAILED: OrderStatus.FAILED,
    JobStatus.PAUSED: OrderStatus.PAUSED,
    JobStatus.PENDING: OrderStatus.WAITING_FOR_LOCAL_WORKER,
}


def pipeline_status(job, *, has_model: bool, has_questions: bool) -> OrderStatus:
    """What the job says about the order, in the order's own words.

    `has_model` and `has_questions` are passed rather than read from the job because
    they are facts about the artifacts a caller has already fetched, and because
    "there are questions" means *readable* questions: an unparseable
    CLARIFICATION_QUESTIONS artifact must not put an order into a state whose page
    then has nothing to render.
    """
    if has_model:
        # The end of the line, and it outranks the job's own status: a completed
        # build whose row has not been swept yet is still a customer with two files.
        return OrderStatus.READY
    if has_questions:
        return OrderStatus.WAITING_FOR_USER_ANSWERS
    if job.status in _STOPPED:
        return _STOPPED[job.status]
    if job.status == JobStatus.LEASED:
        return _LEASED_MEANS.get(job.job_type, OrderStatus.DRAWING_ANALYSIS)
    # COMPLETED with neither a model nor questions. Rare and real: a drawing job
    # that finished with only its analysis, whose next job has not been enqueued.
    # Waiting is the truthful answer and the one that keeps the page polling.
    return OrderStatus.WAITING_FOR_LOCAL_WORKER


def order_status(order, job, *, has_model: bool, has_questions: bool) -> OrderStatus:
    """The answer the API gives, with the order's decisions on top of the job's work.

    A decision outranks an observation. An operator cancelling an order does not
    reach into the worker and stop the build — the build finishes and its artifacts
    are stored — and the order is still cancelled. The same for an order held for
    manual review: the pipeline may have plenty to say and none of it is what the
    customer should be told.

    An order this service has no row for at all (created before the table existed,
    and known only by its tracking file) is `None`, and then the job answers alone.
    """
    if order is not None and is_decided(order.status):
        return order.status
    return pipeline_status(job, has_model=has_model, has_questions=has_questions)


__all__ = ["order_status", "pipeline_status"]
