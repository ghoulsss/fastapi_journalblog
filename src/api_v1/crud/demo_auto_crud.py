# from sqlalchemy import select
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy.orm import selectinload, joinedload

# from src.db.models import User, Article, Tag, Category, CheckAuthor


# async def get_articles_full_with_users(session: AsyncSession) -> list[Article]:
#     stmt = (
#         select(Article)
#         .options(
#             selectinload(Article.tag),
#             selectinload(Article.user),
#             joinedload(Article.category),
#         )
#         .order_by(Article.id)
#     )
#     data = await session.scalars(stmt)
#     return list(data)


# async def demo_m2m(
#     session: AsyncSession,
# ):
#     users = await get_users_with_articles(session)
#     for i, user in enumerate(users):
#         print(
#             f"{i+1}. username: {user.username}, email: {user.email}, авторство: {user.is_author.value}, articles:",
#         )
#         for article in user.article:
#             print(
#                 "-",
#                 f"Заголовок - {article.title},",  # контент - {article.content}, {article.tag},{article.category},{article.created_at}",
#             )
#     articles = await get_articles_full(session)
#     for i, article in enumerate(articles):
#         print(
#             f"{i+1}. Пост: {article.title}, Теги: {";".join(tag.name for tag in article.tag)}, Категории: {article.category.name}"
#         )
