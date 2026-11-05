"""
Simple Chess  -  play against yourself or against a computer opponent.

* 100% offline, no third-party packages (only Python's built-in tkinter).
* Full chess rules: castling, en passant, promotion, check, checkmate,
  stalemate, threefold repetition, 50-move rule, insufficient material.
"""

import json
import os
import random
import sys
import threading
import time

# =====================================================================
#  CHESS ENGINE
# =====================================================================

EMPTY, P, N, B, R, Q, K = 0, 1, 2, 3, 4, 5, 6      # piece types
WHITE, BLACK = 1, -1                                # white = +, black = -
FILES = "abcdefgh"
LETTER = {N: "N", B: "B", R: "R", Q: "Q", K: "K"}

# Squares are numbered 0..63 with a8 = 0, h8 = 7, a1 = 56, h1 = 63.
START_BOARD = (
    [-R, -N, -B, -Q, -K, -B, -N, -R]
    + [-P] * 8
    + [0] * 32
    + [P] * 8
    + [R, N, B, Q, K, B, N, R]
)


def sq_name(s):
    return FILES[s & 7] + str(8 - (s >> 3))


def _build_tables():
    knight = [[] for _ in range(64)]
    king = [[] for _ in range(64)]
    rays = [[[] for _ in range(8)] for _ in range(64)]
    # 0 N, 1 S, 2 E, 3 W (rook-like)   4 NE, 5 NW, 6 SE, 7 SW (bishop-like)
    dirs = [(-1, 0), (1, 0), (0, 1), (0, -1), (-1, 1), (-1, -1), (1, 1), (1, -1)]
    for s in range(64):
        r, c = s >> 3, s & 7
        for dr, dc in ((-2, -1), (-2, 1), (-1, -2), (-1, 2),
                       (1, -2), (1, 2), (2, -1), (2, 1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < 8 and 0 <= cc < 8:
                knight[s].append(rr * 8 + cc)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = r + dr, c + dc
                if 0 <= rr < 8 and 0 <= cc < 8:
                    king[s].append(rr * 8 + cc)
        for d, (dr, dc) in enumerate(dirs):
            rr, cc = r + dr, c + dc
            while 0 <= rr < 8 and 0 <= cc < 8:
                rays[s][d].append(rr * 8 + cc)
                rr += dr
                cc += dc
    return knight, king, rays


KNIGHT_T, KING_T, RAYS = _build_tables()

# Castling rights bits: 1 = white king-side, 2 = white queen-side,
#                       4 = black king-side, 8 = black queen-side
CASTLE_MASK = [15] * 64
CASTLE_MASK[60] = 12
CASTLE_MASK[63] = 14
CASTLE_MASK[56] = 13
CASTLE_MASK[4] = 3
CASTLE_MASK[7] = 11
CASTLE_MASK[0] = 7


class Position:
    def __init__(self):
        self.board = list(START_BOARD)
        self.turn = WHITE
        self.castling = 15
        self.ep = -1            # en-passant target square, or -1
        self.half = 0           # half-move clock (50-move rule)
        self.full = 1
        self.king = {WHITE: 60, BLACK: 4}

    # -- helpers ------------------------------------------------------
    def copy(self):
        p = Position.__new__(Position)
        p.board = list(self.board)
        p.turn = self.turn
        p.castling = self.castling
        p.ep = self.ep
        p.half = self.half
        p.full = self.full
        p.king = dict(self.king)
        return p

    @staticmethod
    def from_fen(fen):
        parts = fen.split()
        pos = Position()
        pos.board = [0] * 64
        r = c = 0
        for ch in parts[0]:
            if ch == "/":
                r += 1
                c = 0
            elif ch.isdigit():
                c += int(ch)
            else:
                v = {"p": P, "n": N, "b": B, "r": R, "q": Q, "k": K}[ch.lower()]
                sign = WHITE if ch.isupper() else BLACK
                pos.board[r * 8 + c] = v * sign
                if v == K:
                    pos.king[sign] = r * 8 + c
                c += 1
        pos.turn = WHITE if parts[1] == "w" else BLACK
        pos.castling = 0
        for ch in parts[2]:
            pos.castling |= {"K": 1, "Q": 2, "k": 4, "q": 8}.get(ch, 0)
        if len(parts) > 3 and parts[3] != "-":
            pos.ep = (8 - int(parts[3][1])) * 8 + FILES.index(parts[3][0])
        pos.half = int(parts[4]) if len(parts) > 4 else 0
        pos.full = int(parts[5]) if len(parts) > 5 else 1
        return pos

    # -- attack detection --------------------------------------------
    def attacked(self, sq, by):
        """Is `sq` attacked by any piece of colour `by`?"""
        b = self.board
        r, c = sq >> 3, sq & 7
        pr = r + 1 if by == WHITE else r - 1      # row where an attacking pawn sits
        if 0 <= pr < 8:
            if c > 0 and b[pr * 8 + c - 1] == P * by:
                return True
            if c < 7 and b[pr * 8 + c + 1] == P * by:
                return True
        n = N * by
        for t in KNIGHT_T[sq]:
            if b[t] == n:
                return True
        k = K * by
        for t in KING_T[sq]:
            if b[t] == k:
                return True
        rook, bishop, queen = R * by, B * by, Q * by
        rays = RAYS[sq]
        for d in range(4):
            for t in rays[d]:
                v = b[t]
                if v:
                    if v == rook or v == queen:
                        return True
                    break
        for d in range(4, 8):
            for t in rays[d]:
                v = b[t]
                if v:
                    if v == bishop or v == queen:
                        return True
                    break
        return False

    def in_check(self):
        return self.attacked(self.king[self.turn], -self.turn)

    # -- move generation ---------------------------------------------
    def pseudo(self, captures_only=False):
        """Pseudo-legal moves as (from, to, promotion). Own king may be left in check."""
        b = self.board
        us = self.turn
        moves = []
        add = moves.append
        for s in range(64):
            p = b[s]
            if p * us <= 0:
                continue
            a = p if p > 0 else -p
            if a == P:
                r, c = s >> 3, s & 7
                dr = -us
                fwd = s + dr * 8
                promo_row = 0 if us == WHITE else 7
                start_row = 6 if us == WHITE else 1
                if b[fwd] == 0:
                    if (fwd >> 3) == promo_row:
                        for pr in (Q, R, B, N):
                            add((s, fwd, pr))
                    elif not captures_only:
                        add((s, fwd, 0))
                        if r == start_row and b[fwd + dr * 8] == 0:
                            add((s, fwd + dr * 8, 0))
                for dc in (-1, 1):
                    nc = c + dc
                    if 0 <= nc < 8:
                        t = fwd + dc
                        if b[t] * us < 0 or (t == self.ep and b[t] == 0):
                            if (t >> 3) == promo_row:
                                for pr in (Q, R, B, N):
                                    add((s, t, pr))
                            else:
                                add((s, t, 0))
            elif a == N:
                for t in KNIGHT_T[s]:
                    v = b[t]
                    if v * us <= 0 and (v != 0 or not captures_only):
                        add((s, t, 0))
            elif a == K:
                for t in KING_T[s]:
                    v = b[t]
                    if v * us <= 0 and (v != 0 or not captures_only):
                        add((s, t, 0))
                if not captures_only:
                    self._castle_moves(s, us, add)
            else:
                lo, hi = (0, 4) if a == R else (4, 8) if a == B else (0, 8)
                rays = RAYS[s]
                for d in range(lo, hi):
                    for t in rays[d]:
                        v = b[t]
                        if v == 0:
                            if not captures_only:
                                add((s, t, 0))
                        else:
                            if v * us < 0:
                                add((s, t, 0))
                            break
        return moves

    def _castle_moves(self, s, us, add):
        b = self.board
        if us == WHITE:
            if s != 60:
                return
            ks, qs, home = 1, 2, 60
        else:
            if s != 4:
                return
            ks, qs, home = 4, 8, 4
        if not (self.castling & (ks | qs)):
            return
        enemy = -us
        if self.attacked(home, enemy):
            return
        if self.castling & ks:
            if (b[home + 3] == R * us and b[home + 1] == 0 and b[home + 2] == 0
                    and not self.attacked(home + 1, enemy)
                    and not self.attacked(home + 2, enemy)):
                add((home, home + 2, 0))
        if self.castling & qs:
            if (b[home - 4] == R * us and b[home - 1] == 0 and b[home - 2] == 0
                    and b[home - 3] == 0
                    and not self.attacked(home - 1, enemy)
                    and not self.attacked(home - 2, enemy)):
                add((home, home - 2, 0))

    def legal_moves(self):
        res = []
        us = self.turn
        for m in self.pseudo():
            u = self.make(m)
            if not self.attacked(self.king[us], -us):
                res.append(m)
            self.unmake(m, u)
        return res

    # -- make / unmake -----------------------------------------------
    def make(self, m):
        f, t, pr = m
        b = self.board
        us = self.turn
        piece = b[f]
        a = piece if piece > 0 else -piece
        cap_sq = t
        captured = b[t]
        if a == P and captured == 0 and (f & 7) != (t & 7):     # en passant
            cap_sq = (f & ~7) | (t & 7)
            captured = b[cap_sq]
            b[cap_sq] = 0
        undo = (piece, captured, cap_sq, self.ep, self.castling, self.half, self.full)
        b[f] = 0
        b[t] = pr * us if pr else piece
        if a == K:
            self.king[us] = t
            if t - f == 2:
                b[f + 1] = b[f + 3]
                b[f + 3] = 0
            elif f - t == 2:
                b[f - 1] = b[f - 4]
                b[f - 4] = 0
        self.ep = (f + t) // 2 if (a == P and abs(t - f) == 16) else -1
        self.castling &= CASTLE_MASK[f] & CASTLE_MASK[t]
        self.half = 0 if (a == P or captured) else self.half + 1
        if us == BLACK:
            self.full += 1
        self.turn = -us
        return undo

    def unmake(self, m, undo):
        f, t, pr = m
        piece, captured, cap_sq, ep, castling, half, full = undo
        us = -self.turn
        self.turn = us
        b = self.board
        b[t] = 0
        b[f] = piece
        b[cap_sq] = captured
        if (piece if piece > 0 else -piece) == K:
            self.king[us] = f
            if t - f == 2:
                b[f + 3] = b[f + 1]
                b[f + 1] = 0
            elif f - t == 2:
                b[f - 4] = b[f - 1]
                b[f - 1] = 0
        self.ep = ep
        self.castling = castling
        self.half = half
        self.full = full

    # -- misc ----------------------------------------------------------
    def key(self):
        """Hashable snapshot used for repetition detection."""
        ep = self.ep
        if ep != -1:
            us = self.turn
            r, c = ep >> 3, ep & 7
            pr = r + us
            ok = False
            for dc in (-1, 1):
                if 0 <= c + dc < 8 and 0 <= pr < 8 and self.board[pr * 8 + c + dc] == P * us:
                    ok = True
            if not ok:
                ep = -1
        return (tuple(self.board), self.turn, self.castling, ep)

    def insufficient_material(self):
        others = [(s, v) for s, v in enumerate(self.board) if v and abs(v) != K]
        if not others:
            return True
        if any(abs(v) in (P, R, Q) for _, v in others):
            return False
        if len(others) == 1:
            return True                         # lone knight or bishop
        if all(abs(v) == B for _, v in others):  # only bishops
            colours = {((s >> 3) + (s & 7)) % 2 for s, _ in others}
            return len(colours) == 1
        return False


def perft(pos, depth):
    if depth == 0:
        return 1
    n = 0
    us = pos.turn
    for m in pos.pseudo():
        u = pos.make(m)
        if not pos.attacked(pos.king[us], -us):
            n += perft(pos, depth - 1)
        pos.unmake(m, u)
    return n


# =====================================================================
#  GAME (history, notation, results)
# =====================================================================

class Game:
    def __init__(self):
        self.pos = Position()
        self.stack = []                  # (move, undo, san)
        self.keys = [self.pos.key()]
        self._legal = None

    def legal(self):
        if self._legal is None:
            self._legal = self.pos.legal_moves()
        return self._legal

    def push(self, m):
        pos = self.pos
        legal = self.legal()
        f, t, pr = m
        p = pos.board[f]
        a = abs(p)
        if a == K and abs(t - f) == 2:
            s = "O-O" if t > f else "O-O-O"
        else:
            cap = pos.board[t] != 0 or (a == P and (f & 7) != (t & 7))
            if a == P:
                s = (FILES[f & 7] + "x" if cap else "") + sq_name(t)
            else:
                s = LETTER[a]
                others = [x for x in legal
                          if x[1] == t and x[0] != f and pos.board[x[0]] == p]
                if others:
                    if all((x[0] & 7) != (f & 7) for x in others):
                        s += FILES[f & 7]
                    elif all((x[0] >> 3) != (f >> 3) for x in others):
                        s += str(8 - (f >> 3))
                    else:
                        s += FILES[f & 7] + str(8 - (f >> 3))
                if cap:
                    s += "x"
                s += sq_name(t)
            if pr:
                s += "=" + LETTER[pr]
        u = pos.make(m)
        self._legal = None
        if pos.in_check():
            s += "#" if not self.legal() else "+"
        self.stack.append((m, u, s))
        self.keys.append(pos.key())

    def pop(self):
        if not self.stack:
            return
        m, u, _ = self.stack.pop()
        self.pos.unmake(m, u)
        self.keys.pop()
        self._legal = None

    def result(self):
        """Return None while the game goes on, otherwise a message."""
        pos = self.pos
        if not self.legal():
            if pos.in_check():
                winner = "Black" if pos.turn == WHITE else "White"
                return "Checkmate! " + winner + " wins."
            return "Stalemate - the game is a draw."
        if pos.insufficient_material():
            return "Draw - not enough pieces left to checkmate."
        if self.keys.count(self.keys[-1]) >= 3:
            return "Draw by threefold repetition."
        if pos.half >= 100:
            return "Draw by the 50-move rule."
        return None


# =====================================================================
#  COMPUTER OPPONENT
# =====================================================================

VAL = [0, 100, 320, 330, 500, 900, 0]
PHASE = [0, 0, 1, 1, 2, 4, 0]

# Piece-square tables from White's point of view (index 0 = a8).
_PST_P = [0, 0, 0, 0, 0, 0, 0, 0,
          50, 50, 50, 50, 50, 50, 50, 50,
          10, 10, 20, 30, 30, 20, 10, 10,
          5, 5, 10, 25, 25, 10, 5, 5,
          0, 0, 0, 20, 20, 0, 0, 0,
          5, -5, -10, 0, 0, -10, -5, 5,
          5, 10, 10, -20, -20, 10, 10, 5,
          0, 0, 0, 0, 0, 0, 0, 0]
_PST_N = [-50, -40, -30, -30, -30, -30, -40, -50,
          -40, -20, 0, 0, 0, 0, -20, -40,
          -30, 0, 10, 15, 15, 10, 0, -30,
          -30, 5, 15, 20, 20, 15, 5, -30,
          -30, 0, 15, 20, 20, 15, 0, -30,
          -30, 5, 10, 15, 15, 10, 5, -30,
          -40, -20, 0, 5, 5, 0, -20, -40,
          -50, -40, -30, -30, -30, -30, -40, -50]
_PST_B = [-20, -10, -10, -10, -10, -10, -10, -20,
          -10, 0, 0, 0, 0, 0, 0, -10,
          -10, 0, 5, 10, 10, 5, 0, -10,
          -10, 5, 5, 10, 10, 5, 5, -10,
          -10, 0, 10, 10, 10, 10, 0, -10,
          -10, 10, 10, 10, 10, 10, 10, -10,
          -10, 5, 0, 0, 0, 0, 5, -10,
          -20, -10, -10, -10, -10, -10, -10, -20]
_PST_R = [0, 0, 0, 0, 0, 0, 0, 0,
          5, 10, 10, 10, 10, 10, 10, 5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          0, 0, 0, 5, 5, 0, 0, 0]
_PST_Q = [-20, -10, -10, -5, -5, -10, -10, -20,
          -10, 0, 0, 0, 0, 0, 0, -10,
          -10, 0, 5, 5, 5, 5, 0, -10,
          -5, 0, 5, 5, 5, 5, 0, -5,
          0, 0, 5, 5, 5, 5, 0, -5,
          -10, 5, 5, 5, 5, 5, 0, -10,
          -10, 0, 5, 0, 0, 0, 0, -10,
          -20, -10, -10, -5, -5, -10, -10, -20]
_PST_K_MID = [-30, -40, -40, -50, -50, -40, -40, -30,
              -30, -40, -40, -50, -50, -40, -40, -30,
              -30, -40, -40, -50, -50, -40, -40, -30,
              -30, -40, -40, -50, -50, -40, -40, -30,
              -20, -30, -30, -40, -40, -30, -30, -20,
              -10, -20, -20, -20, -20, -20, -20, -10,
              20, 20, 0, 0, 0, 0, 20, 20,
              20, 30, 10, 0, 0, 10, 30, 20]
_PST_K_END = [-50, -40, -30, -20, -20, -30, -40, -50,
              -30, -20, -10, 0, 0, -10, -20, -30,
              -30, -10, 20, 30, 30, 20, -10, -30,
              -30, -10, 30, 40, 40, 30, -10, -30,
              -30, -10, 30, 40, 40, 30, -10, -30,
              -30, -10, 20, 30, 30, 20, -10, -30,
              -30, -30, 0, 0, 0, 0, -30, -30,
              -50, -30, -30, -30, -30, -30, -30, -50]
PST = [None, _PST_P, _PST_N, _PST_B, _PST_R, _PST_Q]
CENTER_DIST = [max(3 - (s >> 3), (s >> 3) - 4) + max(3 - (s & 7), (s & 7) - 4)
               for s in range(64)]

INF = 10 ** 7
MATE = 100000


class Timeout(Exception):
    pass


def evaluate(pos):
    """Static score in centipawns from the point of view of the side to move."""
    b = pos.board
    score = 0
    phase = 0
    for s in range(64):
        p = b[s]
        if p == 0:
            continue
        if p > 0:
            if p != K:
                score += VAL[p] + PST[p][s]
                phase += PHASE[p]
        else:
            a = -p
            if a != K:
                score -= VAL[a] + PST[a][s ^ 56]
                phase += PHASE[a]
    wk, bk = pos.king[WHITE], pos.king[BLACK]
    endgame = phase <= 6
    kt = _PST_K_END if endgame else _PST_K_MID
    score += kt[wk] - kt[bk ^ 56]
    if endgame and abs(score) > 200:
        # Help the engine to actually deliver mate: push the losing king to the
        # edge and bring the winning king close.
        winner = WHITE if score > 0 else BLACK
        loser_k = bk if winner == WHITE else wk
        dist = abs((wk >> 3) - (bk >> 3)) + abs((wk & 7) - (bk & 7))
        bonus = CENTER_DIST[loser_k] * 10 + (14 - dist) * 4
        score += bonus if winner == WHITE else -bonus
    return score if pos.turn == WHITE else -score


class Searcher:
    def __init__(self, pos, max_depth, time_limit, noise):
        self.pos = pos
        self.max_depth = max_depth
        self.time_limit = time_limit
        self.noise = noise
        self.nodes = 0
        self.deadline = 0

    def _mscore(self, m):
        b = self.pos.board
        f, t, pr = m
        s = 0
        v = abs(b[t])
        if v:
            s = 10 * VAL[v] - VAL[abs(b[f])]
        elif abs(b[f]) == P and (f & 7) != (t & 7):
            s = 10 * VAL[P] - VAL[P]
        if pr:
            s += VAL[pr]
        return s

    def order(self, moves, first=None):
        moves = sorted(moves, key=self._mscore, reverse=True)
        if first is not None and first in moves:
            moves.remove(first)
            moves.insert(0, first)
        return moves

    def _tick(self):
        self.nodes += 1
        if (self.nodes & 255) == 0 and time.time() > self.deadline:
            raise Timeout()

    def qsearch(self, alpha, beta, qd):
        self._tick()
        pos = self.pos
        stand = evaluate(pos)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        if qd >= 6:
            return alpha
        for m in self.order(pos.pseudo(captures_only=True)):
            u = pos.make(m)
            if pos.attacked(pos.king[-pos.turn], pos.turn):
                pos.unmake(m, u)
                continue
            score = -self.qsearch(-beta, -alpha, qd + 1)
            pos.unmake(m, u)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def search(self, depth, alpha, beta, ply):
        self._tick()
        pos = self.pos
        if pos.half >= 100:
            return 0
        in_check = pos.in_check()
        if in_check and ply < 12:
            depth += 1
        if depth <= 0:
            return self.qsearch(alpha, beta, 0)
        best = -INF
        legal = 0
        for m in self.order(pos.pseudo()):
            u = pos.make(m)
            if pos.attacked(pos.king[-pos.turn], pos.turn):
                pos.unmake(m, u)
                continue
            legal += 1
            score = -self.search(depth - 1, -beta, -alpha, ply + 1)
            pos.unmake(m, u)
            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        if legal == 0:
            return (-MATE + ply) if in_check else 0
        return best

    def best_move(self):
        pos = self.pos
        root = pos.legal_moves()
        if not root:
            return None
        if len(root) == 1:
            return root[0]
        self.deadline = time.time() + self.time_limit
        full_window = self.noise > 0
        best = random.choice(root) if full_window else self.order(root)[0]
        first_depth = self.max_depth if full_window else 1
        try:
            for depth in range(first_depth, self.max_depth + 1):
                alpha = -INF
                scores = []
                cur = None
                moves = self.order(root, None if full_window else best)
                for m in moves:
                    u = pos.make(m)
                    if full_window:
                        sc = -self.search(depth - 1, -INF, INF, 1)
                    else:
                        sc = -self.search(depth - 1, -INF, -alpha, 1)
                    pos.unmake(m, u)
                    scores.append((sc, m))
                    if sc > alpha:
                        alpha = sc
                        cur = m
                if full_window:
                    top = max(s for s, _ in scores)
                    if top > MATE - 100:
                        best = [m for s, m in scores if s == top][0]
                    else:
                        best = max(scores,
                                   key=lambda x: x[0] + random.uniform(-self.noise, self.noise))[1]
                else:
                    best = cur
                    if alpha > MATE - 100:
                        break
        except Timeout:
            pass
        return best


LEVELS = {
    "Beginner": dict(max_depth=1, time_limit=1.0, noise=250),
    "Easy":     dict(max_depth=2, time_limit=2.0, noise=60),
    "Medium":   dict(max_depth=4, time_limit=2.0, noise=0),
    "Hard":     dict(max_depth=8, time_limit=6.0, noise=0),
}


# =====================================================================
#  SETTINGS
# =====================================================================

THEMES = {
    "Classic Green": ("#EEEED2", "#769656"),
    "Brown Wood":    ("#F0D9B5", "#B58863"),
    "Blue Ice":      ("#DEE3E6", "#8CA2AD"),
    "Gray":          ("#E6E6E6", "#9A9A9A"),
}

DEFAULTS = {
    "flip_board": True,        # flip after every move (two-player mode)
    "show_legal": True,        # dots on squares the selected piece can reach
    "show_last": True,         # highlight the last move
    "show_coords": True,       # a-h / 1-8 labels
    "auto_queen": False,       # promote to queen without asking
    "theme": "Classic Green",
    "mode": "human",           # "human" (two players) or "bot"
    "player_color": "White",   # White / Black / Random   (vs computer)
    "difficulty": "Medium",
}


def settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "SimpleChess")
    return folder, os.path.join(folder, "settings.json")


def load_settings():
    s = dict(DEFAULTS)
    try:
        _, path = settings_path()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for k, v in data.items():
            if k in DEFAULTS and type(v) is type(DEFAULTS[k]):
                s[k] = v
        if s["theme"] not in THEMES:
            s["theme"] = DEFAULTS["theme"]
        if s["difficulty"] not in LEVELS:
            s["difficulty"] = DEFAULTS["difficulty"]
        if s["mode"] not in ("human", "bot"):
            s["mode"] = "human"
        if s["player_color"] not in ("White", "Black", "Random"):
            s["player_color"] = "White"
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        folder, path = settings_path()
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(s, fh, indent=2)
    except Exception:
        pass


# =====================================================================
#  USER INTERFACE
# =====================================================================

GLYPH = {P: "\u265F", N: "\u265E", B: "\u265D", R: "\u265C", Q: "\u265B", K: "\u265A"}
SEL_COLOR = "#BACA44"
LAST_LIGHT, LAST_DARK = "#F5EB82", "#D9C94A"
CHECK_COLOR = "#E8605A"
FONT = "Segoe UI"


class ChessApp:
    def __init__(self, root, tk, ttk, messagebox):
        self.tk, self.ttk, self.messagebox = tk, ttk, messagebox
        self.root = root
        root.title("Simple Chess")
        root.geometry("920x660")
        root.minsize(780, 560)

        self.settings = load_settings()
        self.game = Game()
        self.mode = "human"
        self.human_color = WHITE
        self.bot_color = None
        self.difficulty = self.settings["difficulty"]
        self.flipped = False
        self.selected = None
        self.legal = []
        self.in_check = False
        self.over = None
        self.announced = False
        self.thinking = False
        self.token = 0
        self.result = None
        self.poll_id = None
        self.geom = (0, 0, 40)

        self._build_widgets()
        root.bind("<Control-n>", lambda e: self.open_new_game())
        root.bind("<Control-z>", lambda e: self.undo())
        root.bind("<f>", lambda e: self.flip())
        root.bind("<F>", lambda e: self.flip())

        color = {"White": WHITE, "Black": BLACK}.get(self.settings["player_color"], "Random")
        self.new_game(self.settings["mode"], color, self.settings["difficulty"], save=False)

    # ---------------- widgets ----------------
    def _build_widgets(self):
        tk, ttk = self.tk, self.ttk
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(root, highlightthickness=0, bg="#F2F2F2")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self.on_click)

        panel = ttk.Frame(root, padding=12)
        panel.grid(row=0, column=1, sticky="ns")
        self.status = ttk.Label(panel, text="", font=(FONT, 14, "bold"),
                                wraplength=230, justify="left")
        self.status.pack(anchor="w", fill="x")
        self.subtitle = ttk.Label(panel, text="", font=(FONT, 10),
                                  wraplength=230, justify="left", foreground="#555555")
        self.subtitle.pack(anchor="w", fill="x", pady=(2, 10))

        for text, cmd in (("New Game", self.open_new_game),
                          ("Undo Move", self.undo),
                          ("Flip Board", self.flip),
                          ("Settings", self.open_settings)):
            ttk.Button(panel, text=text, command=cmd).pack(fill="x", pady=3)

        ttk.Label(panel, text="Moves", font=(FONT, 10, "bold")).pack(anchor="w", pady=(12, 2))
        box = ttk.Frame(panel)
        box.pack(fill="both", expand=True)
        self.moves_text = tk.Text(box, width=26, height=14, state="disabled", wrap="word",
                                  font=("Consolas", 10), relief="solid", borderwidth=1)
        sb = ttk.Scrollbar(box, command=self.moves_text.yview)
        self.moves_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.moves_text.pack(side="left", fill="both", expand=True)
        ttk.Label(panel, text="Shortcuts: Ctrl+N new, Ctrl+Z undo, F flip",
                  font=(FONT, 8), foreground="#777777").pack(anchor="w", pady=(8, 0))

    # ---------------- game control ----------------
    def new_game(self, mode, color, difficulty, save=True):
        self.cancel_bot()
        if color == "Random":
            color = random.choice((WHITE, BLACK))
        self.game = Game()
        self.mode = mode
        self.difficulty = difficulty
        self.human_color = color
        self.bot_color = -color if mode == "bot" else None
        self.flipped = (color == BLACK) if mode == "bot" else False
        self.selected = None
        self.over = None
        self.announced = False
        if save:
            self.settings["mode"] = mode
            self.settings["difficulty"] = difficulty
        self.refresh()
        self.maybe_bot()

    def subtitle_text(self):
        if self.mode == "bot":
            side = "White" if self.human_color == WHITE else "Black"
            return "You play " + side + " against the computer (" + self.difficulty + ")."
        return "Two players on this computer."

    def refresh(self):
        g = self.game
        self.legal = g.legal()
        self.in_check = g.pos.in_check()
        self.over = g.result()
        turn = g.pos.turn
        if self.over:
            text = self.over
        elif self.thinking:
            text = "Computer is thinking..."
        else:
            side = "White" if turn == WHITE else "Black"
            if self.mode == "bot":
                text = "Your move" if turn == self.human_color else "Computer's move"
                text += " (" + side + ")"
            else:
                text = side + " to move"
            if self.in_check:
                text += " - Check!"
        self.status.configure(text=text)
        self.subtitle.configure(text=self.subtitle_text())
        self.update_moves()
        self.redraw()
        if self.over and not self.announced:
            self.announced = True
            msg = self.over
            self.root.after(80, lambda: self.messagebox.showinfo("Game over", msg))

    def update_moves(self):
        lines = []
        sans = [s for _, _, s in self.game.stack]
        for i in range(0, len(sans), 2):
            white = sans[i]
            black = sans[i + 1] if i + 1 < len(sans) else ""
            lines.append("%3d. %-9s %s" % (i // 2 + 1, white, black))
        t = self.moves_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", "\n".join(lines))
        t.configure(state="disabled")
        t.see("end")

    def apply_flip_rule(self):
        if self.mode == "human" and self.settings["flip_board"]:
            self.flipped = (self.game.pos.turn == BLACK)

    def play(self, m):
        self.game.push(m)
        self.selected = None
        self.apply_flip_rule()
        self.refresh()
        self.maybe_bot()

    def undo(self):
        g = self.game
        if not g.stack:
            return
        if self.thinking:
            self.cancel_bot()
            g.pop()
        else:
            g.pop()
            if self.mode == "bot":
                while g.stack and g.pos.turn != self.human_color:
                    g.pop()
        self.selected = None
        self.announced = False
        self.apply_flip_rule()
        self.refresh()
        self.maybe_bot()

    def flip(self):
        self.flipped = not self.flipped
        self.redraw()

    # ---------------- computer player ----------------
    def maybe_bot(self):
        if (self.mode == "bot" and not self.over and not self.thinking
                and self.game.pos.turn == self.bot_color):
            self.start_bot()

    def start_bot(self):
        self.thinking = True
        self.token += 1
        tok = self.token
        self.result = None
        pos = self.game.pos.copy()
        cfg = LEVELS[self.difficulty]
        self.status.configure(text="Computer is thinking...")

        def work():
            try:
                move = Searcher(pos, **cfg).best_move()
            except Exception:
                move = None
            self.result = (tok, move)

        threading.Thread(target=work, daemon=True).start()
        self.poll_id = self.root.after(80, self.poll)

    def poll(self):
        self.poll_id = None
        if not self.thinking:
            return
        r = self.result
        if r is not None and r[0] == self.token:
            self.thinking = False
            self.result = None
            move = r[1]
            legal = self.game.legal()
            if move not in legal:                 # safety net, should never happen
                move = random.choice(legal) if legal else None
            if move is not None:
                self.play(move)
            else:
                self.refresh()
        else:
            self.poll_id = self.root.after(80, self.poll)

    def cancel_bot(self):
        self.thinking = False
        self.token += 1
        self.result = None
        if self.poll_id is not None:
            try:
                self.root.after_cancel(self.poll_id)
            except Exception:
                pass
            self.poll_id = None

    # ---------------- board input ----------------
    def square_at(self, x, y):
        ox, oy, sq = self.geom
        dc, dr = (x - ox) // sq, (y - oy) // sq
        if not (0 <= dc < 8 and 0 <= dr < 8):
            return None
        if self.flipped:
            dr, dc = 7 - dr, 7 - dc
        return int(dr * 8 + dc)

    def on_click(self, event):
        if self.over or self.thinking:
            return
        pos = self.game.pos
        if self.mode == "bot" and pos.turn != self.human_color:
            return
        s = self.square_at(event.x, event.y)
        if s is None:
            return
        if self.selected is not None:
            options = [m for m in self.legal if m[0] == self.selected and m[1] == s]
            if options:
                if len(options) > 1:                         # promotion
                    if self.settings["auto_queen"]:
                        choice = Q
                    else:
                        choice = self.ask_promotion()
                    options = [m for m in options if m[2] == choice]
                self.play(options[0])
                return
        if pos.board[s] * pos.turn > 0:
            self.selected = None if self.selected == s else s
        else:
            self.selected = None
        self.redraw()

    def ask_promotion(self):
        tk, ttk = self.tk, self.ttk
        top = tk.Toplevel(self.root)
        top.title("Promote pawn")
        top.transient(self.root)
        top.resizable(False, False)
        choice = [Q]

        def pick(v):
            choice[0] = v
            top.destroy()

        ttk.Label(top, text="Promote your pawn to:", font=(FONT, 11),
                  padding=(14, 12, 14, 6)).pack()
        row = ttk.Frame(top, padding=(10, 0, 10, 12))
        row.pack()
        for name, v in (("Queen", Q), ("Rook", R), ("Bishop", B), ("Knight", N)):
            ttk.Button(row, text=name, command=lambda v=v: pick(v)).pack(side="left", padx=4)
        top.protocol("WM_DELETE_WINDOW", lambda: pick(Q))
        self.center(top)
        top.grab_set()
        top.wait_window()
        return choice[0]

    # ---------------- drawing ----------------
    def redraw(self):
        c = self.canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 60 or H < 60:
            return
        S = self.settings
        light, dark = THEMES[S["theme"]]
        margin = 26 if S["show_coords"] else 10
        sq = max(16, (min(W, H) - 2 * margin) // 8)
        ox, oy = (W - 8 * sq) // 2, (H - 8 * sq) // 2
        self.geom = (ox, oy, sq)
        pos = self.game.pos
        board = pos.board
        last = None
        if S["show_last"] and self.game.stack:
            last = self.game.stack[-1][0]
        targets = set()
        if S["show_legal"] and self.selected is not None and not self.over:
            targets = {m[1] for m in self.legal if m[0] == self.selected}
        check_sq = pos.king[pos.turn] if self.in_check else None
        fsize = -int(sq * 0.74)
        off = max(1, sq // 40)

        for dr in range(8):
            for dc in range(8):
                r, col = (7 - dr, 7 - dc) if self.flipped else (dr, dc)
                s = r * 8 + col
                is_light = (r + col) % 2 == 0
                color = light if is_light else dark
                if last and s in (last[0], last[1]):
                    color = LAST_LIGHT if is_light else LAST_DARK
                if s == self.selected:
                    color = SEL_COLOR
                if s == check_sq:
                    color = CHECK_COLOR
                x0, y0 = ox + dc * sq, oy + dr * sq
                c.create_rectangle(x0, y0, x0 + sq, y0 + sq, fill=color, outline=color)

        for dr in range(8):
            for dc in range(8):
                r, col = (7 - dr, 7 - dc) if self.flipped else (dr, dc)
                s = r * 8 + col
                x0, y0 = ox + dc * sq, oy + dr * sq
                cx, cy = x0 + sq / 2, y0 + sq / 2
                p = board[s]
                if p:
                    g = GLYPH[abs(p)]
                    if p > 0:
                        for ddx, ddy in ((-off, 0), (off, 0), (0, -off), (0, off),
                                         (-off, -off), (off, off), (-off, off), (off, -off)):
                            c.create_text(cx + ddx, cy + ddy, text=g, fill="#1A1A1A",
                                          font=("Segoe UI Symbol", fsize))
                        c.create_text(cx, cy, text=g, fill="#FFFFFF",
                                      font=("Segoe UI Symbol", fsize))
                    else:
                        c.create_text(cx, cy, text=g, fill="#1A1A1A",
                                      font=("Segoe UI Symbol", fsize))
                if s in targets:
                    if p:
                        m = sq * 0.08
                        c.create_oval(x0 + m, y0 + m, x0 + sq - m, y0 + sq - m,
                                      outline="#3C3C3C", width=max(2, sq // 14))
                    else:
                        rad = sq * 0.13
                        c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                                      fill="#3C3C3C", outline="#3C3C3C")

        if S["show_coords"]:
            for dc in range(8):
                col = 7 - dc if self.flipped else dc
                c.create_text(ox + dc * sq + sq / 2, oy + 8 * sq + 13, text=FILES[col],
                              fill="#444444", font=(FONT, 10, "bold"))
            for dr in range(8):
                r = 7 - dr if self.flipped else dr
                c.create_text(ox - 13, oy + dr * sq + sq / 2, text=str(8 - r),
                              fill="#444444", font=(FONT, 10, "bold"))

    # ---------------- dialogs ----------------
    def center(self, win):
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))

    def open_new_game(self):
        tk, ttk = self.tk, self.ttk
        top = tk.Toplevel(self.root)
        top.title("New Game")
        top.transient(self.root)
        top.resizable(False, False)
        frame = ttk.Frame(top, padding=16)
        frame.pack()

        mode = tk.StringVar(value=self.settings["mode"])
        color = tk.StringVar(value=self.settings["player_color"])
        diff = tk.StringVar(value=self.settings["difficulty"])

        ttk.Label(frame, text="Who do you want to play?", font=(FONT, 11, "bold")).pack(anchor="w")
        ttk.Radiobutton(frame, text="Myself (two players, one computer)",
                        variable=mode, value="human", command=lambda: update()).pack(anchor="w", pady=2)
        ttk.Radiobutton(frame, text="The computer",
                        variable=mode, value="bot", command=lambda: update()).pack(anchor="w", pady=2)

        bot_box = ttk.Frame(frame)
        bot_box.pack(anchor="w", fill="x", pady=(10, 0), padx=(20, 0))
        ttk.Label(bot_box, text="You play as:").grid(row=0, column=0, sticky="w", pady=3)
        color_cb = ttk.Combobox(bot_box, textvariable=color, state="readonly", width=12,
                                values=("White", "Black", "Random"))
        color_cb.grid(row=0, column=1, padx=8)
        ttk.Label(bot_box, text="Difficulty:").grid(row=1, column=0, sticky="w", pady=3)
        diff_cb = ttk.Combobox(bot_box, textvariable=diff, state="readonly", width=12,
                               values=tuple(LEVELS.keys()))
        diff_cb.grid(row=1, column=1, padx=8)

        def update():
            st = "readonly" if mode.get() == "bot" else "disabled"
            color_cb.configure(state=st)
            diff_cb.configure(state=st)

        def start():
            self.settings["player_color"] = color.get()
            self.settings["mode"] = mode.get()
            self.settings["difficulty"] = diff.get()
            save_settings(self.settings)
            top.destroy()
            col = {"White": WHITE, "Black": BLACK}.get(color.get(), "Random")
            self.new_game(mode.get(), col, diff.get())

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(16, 0))
        ttk.Button(btns, text="Start Game", command=start).pack(side="right")
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right", padx=6)
        update()
        self.center(top)
        top.grab_set()

    def open_settings(self):
        tk, ttk = self.tk, self.ttk
        top = tk.Toplevel(self.root)
        top.title("Settings")
        top.transient(self.root)
        top.resizable(False, False)
        frame = ttk.Frame(top, padding=16)
        frame.pack()

        def toggle(key, var):
            self.settings[key] = bool(var.get())
            save_settings(self.settings)
            if key == "flip_board":
                self.apply_flip_rule()
            self.redraw()

        items = (
            ("flip_board", "Flip the board after every move (two-player mode)"),
            ("show_legal", "Show possible moves for the selected piece"),
            ("show_last", "Highlight the last move"),
            ("show_coords", "Show board coordinates (a-h, 1-8)"),
            ("auto_queen", "Always promote pawns to a queen"),
        )
        for key, label in items:
            var = tk.BooleanVar(value=self.settings[key])
            ttk.Checkbutton(frame, text=label, variable=var,
                            command=lambda k=key, v=var: toggle(k, v)).pack(anchor="w", pady=3)

        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=(10, 0), fill="x")
        ttk.Label(row, text="Board colours:").pack(side="left")
        theme = tk.StringVar(value=self.settings["theme"])
        cb = ttk.Combobox(row, textvariable=theme, state="readonly", width=16,
                          values=tuple(THEMES.keys()))
        cb.pack(side="left", padx=8)

        def on_theme(_e=None):
            self.settings["theme"] = theme.get()
            save_settings(self.settings)
            self.redraw()

        cb.bind("<<ComboboxSelected>>", on_theme)

        row2 = ttk.Frame(frame)
        row2.pack(anchor="w", pady=(8, 0), fill="x")
        ttk.Label(row2, text="Computer difficulty:").pack(side="left")
        diff = tk.StringVar(value=self.difficulty)
        cb2 = ttk.Combobox(row2, textvariable=diff, state="readonly", width=12,
                           values=tuple(LEVELS.keys()))
        cb2.pack(side="left", padx=8)

        def on_diff(_e=None):
            self.difficulty = diff.get()
            self.settings["difficulty"] = diff.get()
            save_settings(self.settings)
            self.subtitle.configure(text=self.subtitle_text())

        cb2.bind("<<ComboboxSelected>>", on_diff)
        ttk.Label(frame, text="(Difficulty applies to the computer's next move.)",
                  font=(FONT, 8), foreground="#777777").pack(anchor="w")
        ttk.Button(frame, text="Close", command=top.destroy).pack(anchor="e", pady=(14, 0))
        self.center(top)
        top.grab_set()


def main():
    try:                                    # sharp text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    ChessApp(root, tk, ttk, messagebox)
    root.mainloop()


if __name__ == "__main__":
    main()
