#!/usr/bin/env python -OO
# -*- coding: utf-8 -*-
from __future__ import with_statement
from bs4 import BeautifulSoup
from glob import glob

import argparse
import os
import re
import sqlite3
import sys


def main(args):
    """Loop thru all the games and parse them."""
    if not os.path.isdir(args.dir):
        print "The specified folder is not a directory."
        sys.exit(1)
    NUMBER_OF_FILES = len(os.listdir(args.dir))
    if args.num_of_files:
        NUMBER_OF_FILES = args.num_of_files
    print "Parsing", NUMBER_OF_FILES, "files"
    sql = None
    if not args.stdout:
        sql = sqlite3.connect(args.database)
        sql.execute("""PRAGMA foreign_keys = ON;""")
        sql.execute("""CREATE TABLE airdates(
            game INTEGER PRIMARY KEY,
            airdate TEXT
        );""")
        sql.execute("""CREATE TABLE documents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clue TEXT,
            answer TEXT
        );""")
        sql.execute("""CREATE TABLE categories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE);""")
        sql.execute("""CREATE TABLE clues(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game INTEGER,
            round INTEGER,
            value INTEGER,
            correct INTEGER,
            order_id INTEGER,
            dd INTEGER,
            FOREIGN KEY(id) REFERENCES documents(id),
            FOREIGN KEY(game) REFERENCES airdates(game)
        );""")
        sql.execute("""CREATE TABLE classifications(
            clue_id INTEGER,
            category_id INTEGER,
            FOREIGN KEY(clue_id) REFERENCES clues(id),
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );""")
    for i, file_name in enumerate(glob(os.path.join(args.dir, "*.html")), 1):
        with open(os.path.abspath(file_name)) as f:
            parse_game(f, sql, i)
    if not args.stdout:
        sql.commit()
    print "All done"


def parse_game(f, sql, gid):
    """Parses an entire Jeopardy! game and extract individual clues."""
    bsoup = BeautifulSoup(f, "lxml")
    # The title is in the format: `J! Archive - Show #XXXX, aired 2004-09-16`,
    # where the last part is all that is required
    airdate = bsoup.title.get_text().split()[-1]
    if not parse_round(bsoup, sql, 1, gid, airdate) or not parse_round(bsoup, sql, 2, gid, airdate):
        # One of the rounds does not exist
        pass
    # The final Jeopardy! round
    r = bsoup.find("table", class_="final_round")
    if not r:
        # This game does not have a final clue
        return
    category = r.find("td", class_="category_name").get_text()
    text = r.find("td", class_="clue_text").get_text()
    answer = BeautifulSoup(r.find("div", onmouseover=True).get("onmouseover"), "lxml")
    answer = answer.find("em").get_text()
    # False indicates no preset value for a clue
    insert(sql, [gid, airdate, 3, category, False, text, answer, None, None, None])


def parse_round(bsoup, sql, rnd, gid, airdate):
    """Parses and inserts the list of clues from a whole round."""
    round_id = "jeopardy_round" if rnd == 1 else "double_jeopardy_round"
    r = bsoup.find(id=round_id)
    # The game may not have all the rounds
    if not r:
        return False
    # The list of categories for this round
    categories = [c.get_text() for c in r.find_all("td", class_="category_name")]
    # The x_coord determines which category a clue is in
    # because the categories come before the clues, we will
    # have to match them up with the clues later on.
    x = 0
    for a in r.find_all("td", class_="clue"):
        is_missing = True if not a.get_text().strip() else False
        if not is_missing:
            try:
                value = a.find("td", class_=re.compile("clue_value")).get_text().lstrip("D: $")
            except Exception:
                print("couldn't find value, continuing")
                continue
            try:
                text = a.find("td", class_="clue_text").get_text()
            except Exception:
                pass
            try:
                answer = BeautifulSoup(a.find("div", onmouseover=True).get("onmouseover"), "lxml")
            except Exception:
                pass
            try:
                correct = answer.find("td", class_="wrong") is not None
            except Exception:
                print("couldn't find correctness, continuing")
                continue
            try:
                answer = answer.find("em", class_="correct_response").get_text()
            except Exception:
                pass
            try:
                dd = a.find("td", class_="clue_value_daily_double") is not None
            except Exception:
                print("couldn't find Daily Double, continuing")
            try:
                order_id = int(a.find("td", class_="clue_order_number").string)
            except Exception:
                pass
            insert(sql, [gid, airdate, rnd, categories[x], value, text, answer, correct, dd, order_id])
        # Always update x, even if we skip
        # a clue, as this keeps things in order. there
        # are 6 categories, so once we reach the end,
        # loop back to the beginning category.
        #
        # Using modulus is slower, e.g.:
        #
        # x += 1
        # x %= 6
        #
        x = 0 if x == 5 else x + 1
    return True


def insert(sql, clue):  # TODO
    """Inserts the given clue into the database."""
    # Clue is [game, airdate, round, category, value, clue, answer, correctness, daily_double, order_id]
    # Note that at this point, clue[4] is False if round is 3
    if "\\\'" in clue[6]:
        clue[6] = clue[6].replace("\\\'", "'")
    if "\\\"" in clue[6]:
        clue[6] = clue[6].replace("\\\"", "\"")
    if not sql:
        print clue
        return
    sql.execute(
        "INSERT OR IGNORE INTO airdates VALUES(?, ?);",
        (clue[0], clue[1], )
    )
    sql.execute("INSERT OR IGNORE INTO categories(category) VALUES(?);", (clue[3], ))
    category_id = sql.execute("SELECT id FROM categories WHERE category=?;", (clue[3], )).fetchone()[0]
    clue_id = sql.execute("INSERT INTO documents(clue, answer) VALUES(?, ?);", (clue[5], clue[6], )).lastrowid
    sql.execute("INSERT INTO clues(game, round, value, correct, order_id, dd) VALUES(?, ?, ?, ?, ?, ?);", (clue[0],
                                                        clue[2], clue[4], clue[7], clue[8], clue[9],))  # NOQA
    sql.execute("INSERT INTO classifications VALUES(?, ?)", (clue_id, category_id, ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parse games from the J! Archive website.", add_help=False,
        usage="%(prog)s [options]")
    parser.add_argument("-d", "--dir", dest="dir", metavar="<folder>",
                        help="the directory containing the game files",
                        default="j-archive")
    parser.add_argument("-n", "--number-of-files", dest="num_of_files",
                        metavar="<number>", help="the number of files to parse",
                        type=int)
    parser.add_argument("-f", "--filename", dest="database",
                        metavar="<filename>",
                        help="the filename for the SQLite database",
                        default="clues.db")
    parser.add_argument("--stdout",
                        help="output the clues to stdout and not a database",
                        action="store_true")
    parser.add_argument("--help", action="help",
                        help="show this help message and exit")
    parser.add_argument("--version", action="version", version="2014.09.14")
    main(parser.parse_args())
