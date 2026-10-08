from typing import Any, Optional


class D1Database:
    """
    Small async wrapper around a Cloudflare D1 database binding.

    The database binding is supplied by the Cloudflare Worker environment.
    """

    def __init__(self, db):
        self.db = db

    async def execute(
        self,
        sql: str,
        params: Optional[list[Any]] = None,
    ):
        statement = self.db.prepare(sql)

        if params:
            statement = statement.bind(*params)

        return await statement.run()

    async def all(
        self,
        sql: str,
        params: Optional[list[Any]] = None,
    ) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)

        if params:
            statement = statement.bind(*params)

        result = await statement.all()

        return list(result.results)

    async def first(
        self,
        sql: str,
        params: Optional[list[Any]] = None,
    ) -> Optional[dict[str, Any]]:
        statement = self.db.prepare(sql)

        if params:
            statement = statement.bind(*params)

        result = await statement.first()

        return result


async def init_db(db):
    """
    D1 schema is managed by schema.sql and Wrangler migrations.

    This function intentionally does not create tables at Worker startup.
    """
    return D1Database(db)
