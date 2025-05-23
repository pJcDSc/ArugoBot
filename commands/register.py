import asyncio
import time
import aiosqlite
import random
import discord
import util
import logging
from discord.ext import commands
from main import global_cooldown
from exceptions import DatabaseError

logger = logging.getLogger("bot_logger")

class Register(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.egg = bot.egg

    @commands.command(help="Links your handle")
    @global_cooldown()
    async def register(self, ctx, handle: str = commands.param(description=": Handle to link (e.g. eggag32)")):
        if not isinstance(handle, str):
            await ctx.send("Invalid handle.")
            return
        try: 
            try:
                b = await util.handle_exists_on_cf(self.egg, handle)
                if not b:
                    await ctx.send("Invalid handle.")
                    return
            except Exception as e:
                await ctx.send("Invalid handle.")
                return
            # check that user does not already have a handle
            if await util.handle_linked(ctx.guild.id, ctx.author.id):
                await ctx.send("You already linked a handle (use unlink if you wish to remove it).")
                return
            # check that it is not in the database already (for this server)
            if await util.handle_exists(ctx.guild.id, ctx.author.id, handle):
                await ctx.send("Handle taken in this server.")
                return
            # now give them the verification challenge
            msg = [0]
            ret = await validate_handle(ctx, self.egg, ctx.guild.id, ctx.author.id, handle, msg)
            cont = ""
            if ret == 1:
                cont = f"Handle set to {handle}."
            elif ret == 2:
                cont = "Verification failed."
            elif ret == 3:
                cont = "Handle has been taken (;-; are you trying to break me)."
            elif ret == 4:
                cont = "You already linked a handle (during verification, is this a test?)."
            else:
                cont = "Some error (maybe CF is down)."
            message = await ctx.channel.fetch_message(msg[0])
            reg_embed = discord.Embed(title="Verify your handle", description=cont, color=discord.Color.blue())
            await message.edit(embed=reg_embed)
        except Exception as e:
            logger.error(f"Some error: {e}")
            await ctx.send("Some error occurred.")

    @commands.command(help="Unlinks your handle")
    @global_cooldown()
    async def unlink(self, ctx):
        try:
            if not await util.handle_linked(ctx.guild.id, ctx.author.id):
                await ctx.send("You have not linked a handle.")
                return
            embed = discord.Embed(title="Confirm", description="Are you sure? This action cannot be undone. React with :white_check_mark: within 60 seconds to confirm.", color=discord.Color.blue())
            message = await ctx.send(embed=embed)
            await message.add_reaction("✅")

            def check(reaction, user):
                return user.id == ctx.author.id and str(reaction.emoji) == "✅" and reaction.message.id == message.id

            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=60.0, check=check)
                await unlink(ctx.guild.id, ctx.author.id)
                embed.description = "Account unlinked."
                await message.edit(embed=embed)
            except Exception as e:
                embed.description = "Account not unlinked."
                await message.edit(embed=embed)
        except Exception as e:
            logger.error(f"Some error: {e}")
            await ctx.send("Some error occurred.")


async def setup(bot):
    await bot.add_cog(Register(bot))

async def validate_handle(ctx, egg, server_id: int, user_id: int, handle: str, msg: list):
    if util.problems is None:
        try:
            await util.get_problems()    
        except Exception as e:
            logger.error(f"Failed to get problems: {e}")
            return 5

    problem = util.problems[random.randint(0, len(util.problems) - 1)]
    t = time.time()
    embed = discord.Embed(title="Verify your handle", description=f"Submit a compilation error to the following problem in the next 60 seconds:\nhttps://codeforces.com/problemset/problem/{problem['contestId']}/{problem['index']}", color=discord.Color.blue())
    message = await ctx.send(embed=embed)
    msg[0] = message.id

    await asyncio.sleep(60)
    if not await got_submission(egg, handle, problem, t):
        return 2
    async with aiosqlite.connect(util.path + "bot_data.db") as db:
        try:
            await db.execute("BEGIN TRANSACTION")

            async with db.execute("SELECT handle FROM users WHERE server_id = ? AND handle = ?", (server_id, handle)) as cursor:
                existing_handle = await cursor.fetchone()

            if existing_handle:
                await db.rollback()
                return 3

            async with db.execute("SELECT handle FROM users WHERE server_id = ? AND user_id = ?", (server_id, user_id)) as cursor:
                linked_handle = await cursor.fetchone()

            if linked_handle:
                await db.rollback()
                return 4

            history = "[]"
            rating_history = "[1500]"
            await db.execute(
                "INSERT INTO users (server_id, user_id, handle, rating, history, rating_history) VALUES (?, ?, ?, ?, ?, ?)",
                (server_id, user_id, handle, 1500, history, rating_history)
            )

            await db.commit()
            return 1
        except Exception as e:
            await db.rollback()
            logger.error(f"Transaction failed: {e}")
            return 5

async def got_submission(egg, handle: str, problem, t):
    try:

        response_data = await egg.codeforces("contest.status", {"contestId" : problem["contestId"], "asManager" : "false", "from" : 1, "count" : 10, "handle" : handle})

        if response_data["status"] != "OK":
            return False

        for o in response_data["result"]:
            if o["problem"]["index"] == problem["index"] and o["verdict"] == "COMPILATION_ERROR" and o["contestId"] == problem["contestId"]:
                return o["creationTimeSeconds"] > t

    except Exception as e:
        logger.error(f"Error getting submission, got_submission(): {e}")
        return False

async def unlink(server_id: int, user_id: int):
    try:
        async with aiosqlite.connect(util.path + "bot_data.db") as db:
            await db.execute("DELETE FROM users WHERE server_id = ? AND user_id = ?", (server_id, user_id))
            await db.commit()
    except Exception as e:
        logger.error(f"Database error, unlink(): {e}")
        raise DatabaseError(e)