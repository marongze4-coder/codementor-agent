# backend/api/router.py
# API 路由总入口

from fastapi import APIRouter
from backend.api.v1 import assignment, auth, code_review, defense, qa, unified_chat

api_router = APIRouter()                              # 总路由

# 把每个子 router 带前缀 + 标签聚合进来
api_router.include_router(auth.router,         prefix="/auth",        tags=["认证"])
api_router.include_router(unified_chat.router, prefix="/chat",        tags=["课程智能助手"])
api_router.include_router(qa.router,           prefix="/qa",          tags=["程序设计问答"])
api_router.include_router(assignment.router,   prefix="/assignments", tags=["编程作业评测"])
api_router.include_router(code_review.router,  prefix="/code-review", tags=["代码质量审查"])
api_router.include_router(defense.router,      prefix="/defense",     tags=["项目答辩"])
