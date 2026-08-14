"""Tests de la logique qui casse en silence.

On ne teste pas les appels réseau ici (voir `scripts/check_sources.py`), mais les calculs
dont une erreur ne se voit pas : un compte à rebours faux reste un compte à rebours.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from rtmpix import render
from rtmpix.departures import Board, _fold, _matches_filter
from rtmpix.gtfs import date_to_int, parse_gtfs_time
from rtmpix.planner import Leg, Pattern, latest_departure
from rtmpix.realtime import PARIS, Departure, _hhmm_to_datetime, active_services
from rtmpix.schedule import _as_datetime

# ------------------------------------------------------------------ horaires GTFS

def test_parse_gtfs_time_apres_minuit():
    assert parse_gtfs_time("05:01:42") == 18102
    # 25:03 n'est pas une erreur : c'est 1h03 du service de la veille.
    assert parse_gtfs_time("25:03:00") == 90180
    assert parse_gtfs_time("bidon") is None
    assert parse_gtfs_time("") is None


def test_date_to_int():
    assert date_to_int(date(2026, 8, 14)) == 20260814


def test_active_services(db):
    services = active_services(db, date(2026, 8, 17))
    assert services == ["SVC_ALL"]


def test_active_services_exception(db, db_path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO calendar_dates VALUES (?,?,?)", ("SVC_ALL", 20260817, 2))
    conn.commit()
    conn.close()
    from rtmpix import gtfs

    fresh = gtfs.Database(db_path)
    # exception_type 2 = service supprimé ce jour-là, même si le calendrier le prévoit.
    assert active_services(fresh, date(2026, 8, 17)) == []


# --------------------------------------------------------------- calcul à rebours

def test_latest_departure_avec_correspondance(db):
    pattern = Pattern(
        legs=[
            Leg("R_METRO", "M9", 0, "S_HOME", "Départ", "S_HUB_M", "Le Hub"),
            Leg("R_BUS", "B9", 0, "S_HUB_B", "Métro Le Hub", "S_DEST", "Arrivée"),
        ],
        walk_in_s=300,
        walk_out_s=120,
        transfers_s=[180],
    )
    arrive_by = datetime(2026, 8, 17, 8, 0, tzinfo=PARIS)
    plan = latest_departure(db, pattern, arrive_by, overhead_s=90)

    assert plan is not None
    # Il faut être arrivé à 8h00, marche finale de 2′ comprise : le bus doit arriver
    # au plus tard à 7h58. Bus toutes les 15′ depuis 6h05 + 6′ de trajet.
    assert plan.arrive_at <= arrive_by
    assert plan.legs[-1][1] <= arrive_by - timedelta(seconds=pattern.walk_out_s)
    # Le métro doit laisser le temps de la correspondance.
    metro_arrival = plan.legs[0][1]
    bus_departure = plan.legs[1][0]
    assert (bus_departure - metro_arrival).total_seconds() >= 180
    # Et l'heure de sortie tient compte de la marche et de la préparation.
    assert plan.leave_at == plan.board_at - timedelta(seconds=300 + 90)


def test_latest_departure_trouve_la_course_apres_minuit(db):
    """Une course partie à 25:10 la veille circule encore à 1h10 : elle doit compter."""
    pattern = Pattern(
        legs=[Leg("R_METRO", "M9", 0, "S_HOME", "Départ", "S_HUB_M", "Le Hub")],
        walk_in_s=60,
        walk_out_s=60,
    )
    plan = latest_departure(db, pattern, datetime(2026, 8, 17, 5, 0, tzinfo=PARIS), 90)
    assert plan is not None
    # 25:30 du service du 16 août, soit 1h30 le 17.
    assert plan.legs[0][1] == datetime(2026, 8, 17, 1, 30, tzinfo=PARIS)


def test_latest_departure_impossible_hors_calendrier(db):
    pattern = Pattern(
        legs=[Leg("R_METRO", "M9", 0, "S_HOME", "Départ", "S_HUB_M", "Le Hub")],
        walk_in_s=60,
        walk_out_s=60,
    )
    # Le calendrier de service commence au 1ᵉʳ janvier 2020 et les courses à 6h00 :
    # aucune ne permet d'être arrivé à 5h00 ce jour-là.
    plan = latest_departure(db, pattern, datetime(2020, 1, 1, 5, 0, tzinfo=PARIS), 90)
    assert plan is None


def test_latest_departure_prend_bien_le_dernier(db):
    pattern = Pattern(
        legs=[Leg("R_METRO", "M9", 0, "S_HOME", "Départ", "S_HUB_M", "Le Hub")],
        walk_in_s=0,
        walk_out_s=0,
    )
    # Métro toutes les 10′ depuis 6h00, 20′ de trajet : arrivées à 6h20, 6h30, 6h40…
    plan = latest_departure(db, pattern, datetime(2026, 8, 17, 6, 45, tzinfo=PARIS), 0)
    assert plan is not None
    assert plan.legs[0][1] == datetime(2026, 8, 17, 6, 40, tzinfo=PARIS)


# ------------------------------------------------------------------- affichage

def test_format_lead():
    assert render.format_lead(0) == "GO"
    assert render.format_lead(59) == "GO"
    assert render.format_lead(90) == "1m"
    assert render.format_lead(3660) == "1h01"


def test_urgency_color_change_bien_de_palier():
    assert render.urgency_color(30) == render.NOW
    assert render.urgency_color(90) == render.HURRY
    assert render.urgency_color(200) == render.SOON
    assert render.urgency_color(600) == render.CALM


def test_format_hour():
    assert render.format_hour(datetime(2026, 8, 17, 8, 0)) == "8h"
    assert render.format_hour(datetime(2026, 8, 17, 8, 30)) == "8h30"


def test_slug_sans_accents():
    assert render.slug("Réformés Canebière", 6) == "reform"
    assert render.slug("", 4) == "x"


# ------------------------------------------------------------------ départs

def _dep(line, terminus, station, minutes, realtime=True):
    return Departure(
        station=station,
        line=line,
        terminus=terminus,
        when=datetime(2026, 8, 17, 8, 0, tzinfo=PARIS) + timedelta(minutes=minutes),
        realtime=realtime,
    )


def test_fold_ignore_accents_et_casse():
    assert _fold("Fourragère") == _fold("FOURRAGERE")
    assert _fold(" La Rose ") == "la rose"


def test_matches_filter():
    dep = _dep("M1", "La Fourragère", "Castellane", 5)
    assert _matches_filter(dep, [])
    assert _matches_filter(dep, ["M1"])
    assert _matches_filter(dep, ["M1>Fourragere"])
    assert not _matches_filter(dep, ["M2"])
    assert not _matches_filter(dep, ["M1>La Rose"])


def test_board_catchable_retire_ce_qui_est_perdu():
    now = datetime(2026, 8, 17, 8, 0, tzinfo=PARIS)
    board = Board(line="M1", terminus="X", station="Y", lead_s=300)
    board.departures = [_dep("M1", "X", "Y", 2), _dep("M1", "X", "Y", 10)]
    # Le passage dans 2 minutes est hors d'atteinte avec 5 minutes de préparation.
    assert board.catchable(now) == [300]


# ------------------------------------------------------------------- horaires

def test_hhmm_bascule_sur_le_lendemain():
    now = datetime(2026, 8, 17, 23, 50, tzinfo=PARIS)
    result = _hhmm_to_datetime("00:12", now)
    assert result.day == 18 and result.hour == 0


def test_hhmm_garde_le_passe_proche():
    """Un passage annoncé il y a deux minutes reste aujourd'hui, pas demain."""
    now = datetime(2026, 8, 17, 12, 0, tzinfo=PARIS)
    result = _hhmm_to_datetime("11:58", now)
    assert result.day == 17


# --------------------------------------------------------------------- iCal

def test_as_datetime_journee_entiere():
    assert _as_datetime(date(2026, 9, 1)).hour == 0


def test_as_datetime_naif_devient_paris():
    result = _as_datetime(datetime(2026, 9, 1, 8, 0))
    assert result.tzinfo is not None


# --------------------------------------------------------------------- e-ink

def test_buffer_eink_a_la_bonne_taille():
    from rtmpix import eink

    image = eink.render({"boards": [], "velo": [], "disruptions": [], "journeys": []}, 800, 480)
    assert image.size == (800, 480)
    assert len(eink.to_packed_1bpp(image)) == 800 * 480 // 8
