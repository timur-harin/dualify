# Determine whether this piece can move to the given position (in a single turn).
#
# #  It's never valid to "move" to your present location:
def can_move_to(self, x: int, y: int) -> bool:
        """
        Determine whether this piece can move to the given position (in a single turn).

        pre: (0 <= x < 8) and (0 <= y < 8)

        #  It's never valid to "move" to your present location:
        post: implies((x, y) == (self.x, self.y), not __return__)
        """
        raise NotImplementedError
