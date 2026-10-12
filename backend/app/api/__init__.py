from fastapi import APIRouter

from app.api.routers import (
    agents,
    assignments,
    auth,
    business,
    classes,
    client,
    evaluations,
    feedbacks,
    finance,
    knowledge,
    lessons,
    llm_configs,
    notifications,
    orders,
    packages,
    permissions,
    prompts,
    reports,
    schedules,
    students,
    system_settings,
    trials,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(agents.router)
api_router.include_router(knowledge.router)
api_router.include_router(users.router)
api_router.include_router(students.router)
api_router.include_router(classes.router)
api_router.include_router(packages.router)
api_router.include_router(lessons.router)
api_router.include_router(schedules.router)
api_router.include_router(feedbacks.router)
api_router.include_router(prompts.router)
api_router.include_router(reports.router)
api_router.include_router(assignments.router)
api_router.include_router(orders.router)
api_router.include_router(notifications.router)
api_router.include_router(evaluations.router)
api_router.include_router(permissions.router)
api_router.include_router(system_settings.router)
api_router.include_router(business.router)
api_router.include_router(finance.router)
api_router.include_router(llm_configs.router)
api_router.include_router(client.router)
api_router.include_router(trials.router)
