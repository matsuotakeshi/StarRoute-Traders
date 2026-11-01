BEGIN TRANSACTION;
CREATE TABLE bbs_accounts(bbs_id TEXT NOT NULL, local_user_id TEXT NOT NULL, player_id TEXT NOT NULL UNIQUE REFERENCES players(id) DEFERRABLE INITIALLY DEFERRED, PRIMARY KEY(bbs_id,local_user_id));
INSERT INTO "bbs_accounts" VALUES('local','legacy','legacy');
CREATE TABLE cargo(
 season_id INTEGER NOT NULL, player_id TEXT NOT NULL, goods_id TEXT NOT NULL REFERENCES goods(id),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 1000000000000000),
 PRIMARY KEY(season_id,player_id,goods_id),
 FOREIGN KEY(season_id,player_id) REFERENCES player_state(season_id,player_id));
INSERT INTO "cargo" VALUES(1,'legacy','grain',10);
CREATE TABLE goods(id TEXT PRIMARY KEY, name TEXT NOT NULL, base_price INTEGER NOT NULL CHECK(base_price>0),
 volume INTEGER NOT NULL CHECK(volume>0), production INTEGER NOT NULL CHECK(production>=0),
 volatility_bps INTEGER NOT NULL CHECK(volatility_bps BETWEEN 0 AND 10000));
INSERT INTO "goods" VALUES('grain','星穀',100,1,8,500);
INSERT INTO "goods" VALUES('alloy','軽量合金',200,2,4,800);
INSERT INTO "goods" VALUES('medicine','医療パック',300,1,2,1200);
CREATE TABLE markets(
 season_id INTEGER NOT NULL REFERENCES seasons(id), planet_id TEXT NOT NULL REFERENCES planets(id),
 goods_id TEXT NOT NULL REFERENCES goods(id), price INTEGER NOT NULL CHECK(price BETWEEN 1 AND 1000000000000000),
 stock INTEGER NOT NULL CHECK(stock BETWEEN 0 AND 1000000000000000), PRIMARY KEY(season_id,planet_id,goods_id));
INSERT INTO "markets" VALUES(1,'aurora','grain',60,190);
INSERT INTO "markets" VALUES(1,'aurora','alloy',240,80);
INSERT INTO "markets" VALUES(1,'aurora','medicine',350,50);
INSERT INTO "markets" VALUES(1,'forge','grain',120,70);
INSERT INTO "markets" VALUES(1,'forge','alloy',130,200);
INSERT INTO "markets" VALUES(1,'forge','medicine',340,60);
INSERT INTO "markets" VALUES(1,'haven','grain',90,100);
INSERT INTO "markets" VALUES(1,'haven','alloy',220,80);
INSERT INTO "markets" VALUES(1,'haven','medicine',180,150);
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "metadata" VALUES('schema_version','3');
INSERT INTO "metadata" VALUES('catalog','{"format_version":1,"goods":[{"base_price":100,"id":"grain","name":"星穀","production":8,"volatility_bps":500,"volume":1},{"base_price":200,"id":"alloy","name":"軽量合金","production":4,"volatility_bps":800,"volume":2},{"base_price":300,"id":"medicine","name":"医療パック","production":2,"volatility_bps":1200,"volume":1}],"markets":[{"goods_id":"grain","planet_id":"aurora","price":60,"stock":200},{"goods_id":"alloy","planet_id":"aurora","price":240,"stock":80},{"goods_id":"medicine","planet_id":"aurora","price":350,"stock":50},{"goods_id":"grain","planet_id":"forge","price":120,"stock":70},{"goods_id":"alloy","planet_id":"forge","price":130,"stock":200},{"goods_id":"medicine","planet_id":"forge","price":340,"stock":60},{"goods_id":"grain","planet_id":"haven","price":90,"stock":100},{"goods_id":"alloy","planet_id":"haven","price":220,"stock":80},{"goods_id":"medicine","planet_id":"haven","price":180,"stock":150}],"planets":[{"id":"aurora","name":"オーロラ"},{"id":"forge","name":"フォージ"},{"id":"haven","name":"ヘイヴン"}],"routes":[{"distance":3,"fee":0,"from":"aurora","id":"aurora-forge","is_open":true,"seconds":2,"to":"forge"},{"distance":4,"fee":0,"from":"forge","id":"forge-haven","is_open":true,"seconds":3,"to":"haven"},{"distance":6,"fee":0,"from":"haven","id":"haven-aurora","is_open":true,"seconds":4,"to":"aurora"}],"ships":[{"capacity":20,"id":"sparrow","max_distance":10,"name":"スパロウ","speed":1}],"starting":{"cash":5000,"planet_id":"aurora","ship_id":"sparrow"}}');
CREATE TABLE operation_history(sequence INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id), actor TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL, before_state TEXT NOT NULL, after_state TEXT NOT NULL, game_time INTEGER NOT NULL, UNIQUE(season_id,actor,request_id));
INSERT INTO "operation_history" VALUES(1,1,'legacy','reg','["create_player", ["legacy", "Legacy"]]','{"player_id": "legacy", "handle": "Legacy", "season_id": 1, "cash": 5000, "ship_id": "sparrow", "ship_name": "スパロウ", "capacity": 20, "used_capacity": 0, "planet_id": "aurora", "planet_name": "オーロラ", "destination_id": null, "arrival_at": null, "remaining_seconds": 0, "cargo": []}','null','{"id": "legacy", "handle": "Legacy", "cash": 5000, "ship_id": "sparrow", "planet_id": "aurora", "cargo": {}, "destination_id": null, "arrival_at": null}',100);
INSERT INTO "operation_history" VALUES(2,1,'legacy','buy','["buy_goods", ["legacy", "grain", 10]]','{"side": "buy", "goods_id": "grain", "quantity": 10, "unit_price": 60, "total": 600}','{"id": "legacy", "handle": "Legacy", "cash": 5000, "ship_id": "sparrow", "planet_id": "aurora", "cargo": {}, "destination_id": null, "arrival_at": null}','{"id": "legacy", "handle": "Legacy", "cash": 4400, "ship_id": "sparrow", "planet_id": "aurora", "cargo": {"grain": 10}, "destination_id": null, "arrival_at": null}',100);
INSERT INTO "operation_history" VALUES(3,1,'legacy','go','["depart", ["legacy", "forge"]]','{"destination_id": "forge", "arrival_at": 102, "fee": 0}','{"id": "legacy", "handle": "Legacy", "cash": 4400, "ship_id": "sparrow", "planet_id": "aurora", "cargo": {"grain": 10}, "destination_id": null, "arrival_at": null}','{"id": "legacy", "handle": "Legacy", "cash": 4400, "ship_id": "sparrow", "planet_id": "aurora", "cargo": {"grain": 10}, "destination_id": "forge", "arrival_at": 102}',100);
CREATE TABLE planets(id TEXT PRIMARY KEY, name TEXT NOT NULL);
INSERT INTO "planets" VALUES('aurora','オーロラ');
INSERT INTO "planets" VALUES('forge','フォージ');
INSERT INTO "planets" VALUES('haven','ヘイヴン');
CREATE TABLE player_state(
 season_id INTEGER NOT NULL REFERENCES seasons(id), player_id TEXT NOT NULL REFERENCES players(id),
 cash INTEGER NOT NULL CHECK(cash BETWEEN 0 AND 1000000000000000), ship_id TEXT NOT NULL REFERENCES ships(id),
 planet_id TEXT NOT NULL REFERENCES planets(id), destination_id TEXT REFERENCES planets(id), arrival_at INTEGER,
 PRIMARY KEY(season_id,player_id),
 CHECK((destination_id IS NULL AND arrival_at IS NULL) OR
       (destination_id IS NOT NULL AND arrival_at IS NOT NULL AND arrival_at>=0)));
INSERT INTO "player_state" VALUES(1,'legacy',4400,'sparrow','aurora','forge',102);
CREATE TABLE players(id TEXT PRIMARY KEY, handle TEXT NOT NULL);
INSERT INTO "players" VALUES('legacy','Legacy');
CREATE TABLE preferences(player_id TEXT PRIMARY KEY REFERENCES players(id), language TEXT NOT NULL CHECK(language IN ('ja','en')));
INSERT INTO "preferences" VALUES('legacy','en');
CREATE TABLE routes(
 season_id INTEGER NOT NULL REFERENCES seasons(id), id TEXT NOT NULL,
 from_id TEXT NOT NULL REFERENCES planets(id), to_id TEXT NOT NULL REFERENCES planets(id),
 distance INTEGER NOT NULL CHECK(distance>0), seconds INTEGER NOT NULL CHECK(seconds>0),
 fee INTEGER NOT NULL CHECK(fee BETWEEN 0 AND 1000000000000000), is_open INTEGER NOT NULL CHECK(is_open IN (0,1)),
 PRIMARY KEY(season_id,id), CHECK(from_id<>to_id));
INSERT INTO "routes" VALUES(1,'aurora-forge','aurora','forge',3,2,0,1);
INSERT INTO "routes" VALUES(1,'forge-haven','forge','haven',4,3,0,1);
INSERT INTO "routes" VALUES(1,'haven-aurora','haven','aurora',6,4,0,1);
CREATE TABLE seasons(
 id INTEGER PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('active','closing','closed')),
 started_at INTEGER NOT NULL, game_time INTEGER NOT NULL CHECK(game_time>=0));
INSERT INTO "seasons" VALUES(1,'active',100,100);
CREATE TABLE ship_grades(id TEXT PRIMARY KEY, rank INTEGER NOT NULL UNIQUE CHECK(rank>0));
CREATE TABLE ship_profiles(
            ship_id TEXT PRIMARY KEY REFERENCES ships(id),
            ship_type TEXT CHECK(ship_type IN ('normal','armed_cruiser','engineering')),
            grade_id TEXT REFERENCES ship_grades(id),
            normal_speed INTEGER CHECK(normal_speed>0),
            max_warp_speed INTEGER CHECK(max_warp_speed>0),
            purchase_price INTEGER CHECK(purchase_price>=0),
            insurance_premium INTEGER CHECK(insurance_premium>=0),
            specification_status TEXT NOT NULL CHECK(specification_status IN ('legacy','provisional','confirmed')));
INSERT INTO "ship_profiles" VALUES('sparrow',NULL,NULL,NULL,NULL,NULL,NULL,'legacy');
CREATE TABLE ships(id TEXT PRIMARY KEY, name TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity>0),
 max_distance INTEGER NOT NULL CHECK(max_distance>0), speed INTEGER NOT NULL CHECK(speed>0));
INSERT INTO "ships" VALUES('sparrow','スパロウ',20,10,1);
CREATE UNIQUE INDEX one_active_season ON seasons(status) WHERE status='active';
COMMIT;
