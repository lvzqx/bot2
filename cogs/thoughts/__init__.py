from .post import PostCog
from .list import ListCog
from .search import SearchCog
from .delete import DeleteCog

def setup(bot):
    bot.add_cog(PostCog(bot))
    bot.add_cog(ListCog(bot))
    bot.add_cog(SearchCog(bot))
    bot.add_cog(DeleteCog(bot))
