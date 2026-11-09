PORTNAME=	starroute-traders-master
DISTVERSION=	0.21.0
CATEGORIES=	games
MASTER_SITES=	# Private local distfile: preseed DISTDIR; no invented release URL.
MASTER_SITE_BACKUP=
DISTNAME=	starroute-traders-${DISTVERSION}

MAINTAINER=	ports@localhost
COMMENT=	Private StarRoute Traders master
WWW=		https://github.com/matsuotakeshi/StarRoute-Traders

LICENSE=	Private
LICENSE_NAME=	Private deployment only
LICENSE_TEXT=	Private source; no permission for public redistribution is granted by this port.
LICENSE_PERMS=	auto-accept

USES=		python:3.10+,run
NO_BUILD=	yes
NO_ARCH=	yes
SUB_LIST=	PYTHON_CMD=${PYTHON_CMD}
PLIST_SUB=	PYTHON_CMD=${PYTHON_CMD}
RUN_DEPENDS=	starroute-traders=${PORTVERSION}:games/starroute-traders
USE_RC_SUBR=	starroute_master
SUB_FILES=	master.json pkg-message

pre-fetch:
	@test -f ${DISTDIR}/${DISTNAME}${EXTRACT_SUFX} || (${ECHO_MSG} "Preseed the private local distfile in DISTDIR"; exit 1)

do-install:
	${MKDIR} ${STAGEDIR}${PREFIX}/etc/starroute-traders
	${INSTALL_DATA} ${WRKDIR}/master.json ${STAGEDIR}${PREFIX}/etc/starroute-traders/master.json.sample

.include <bsd.port.mk>
