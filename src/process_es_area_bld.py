#  This work is based on original code developed and copyrighted by TNO 2020.
#  Subsequent contributions are licensed to you by the developers of such code and are
#  made available to the Project under one or several contributor license agreements.
#
#  This work is licensed to you under the Apache License, Version 2.0.
#  You may obtain a copy of the license at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Contributors:
#      TNO         - Initial implementation
#  Manager:
#      TNO

import uuid
import random

from sys import getsizeof
from flask import session
from flask_socketio import emit

from esdl import esdl
from esdl.processing import ESDLGeometry, ESDLAsset, ESDLEnergySystem
from extensions.boundary_service import BoundaryService
from extensions.session_manager import set_handler, get_handler, get_session, set_session_for_esid
from src.esdl_helper import generate_profile_info, get_asset_and_coord_from_port_id
from utils.RDWGSConverter import RDWGSConverter


# ---------------------------------------------------------------------------------------------------------------------
#  Generic functions
# ---------------------------------------------------------------------------------------------------------------------
def send_alert(message):
    print(message)
    emit('alert', message, namespace='/esdl')


# ---------------------------------------------------------------------------------------------------------------------
#   Update asset geometries
# ---------------------------------------------------------------------------------------------------------------------
def calc_center_and_size(coords):
    min_x = float("inf")
    min_y = float("inf")
    max_x = -float("inf")
    max_y = -float("inf")

    for c in coords:
        if c[0] < min_x: min_x = c[0]
        if c[1] < min_y: min_y = c[1]
        if c[0] > max_x: max_x = c[0]
        if c[1] > max_y: max_y = c[1]

    delta_x = max_x - min_x
    delta_y = max_y - min_y

    return [(min_x + max_x) / 2, (min_y + max_y) / 2], delta_x, delta_y


def calc_random_location_around_center(center, delta_x, delta_y, convert_RD_to_WGS):
    geom = esdl.Point()
    x = center[0] + ((-0.5 + random.random()) * delta_x / 2)
    y = center[1] + ((-0.5 + random.random()) * delta_y / 2)
    if convert_RD_to_WGS and (x > 180 or y > 180):  # Assume RD
        rdwgs = RDWGSConverter()
        wgs = rdwgs.fromRdToWgs([x, y])
        geom.lat = wgs[0]
        geom.lon = wgs[1]
    else:
        geom.lat = y
        geom.lon = x
    return geom


def calc_building_assets_location(building):
    """
    Calculate the locations of assets in buildings when they are not given
    The building editor uses a 500x500 pixel canvas
    Rules:
    - Assets of type AbstractConnection are placed in the left-most column
    - Other transport assets in the second column
    - Then production, conversion and storage
    - And finally demand
    """
    num_conns = 0
    num_transp = 0
    num_prod_conv_stor = 0
    num_cons = 0
    for basset in building.asset:
        if isinstance(basset, esdl.AbstractConnection):
            num_conns = num_conns + 1
        elif isinstance(basset, esdl.Transport):
            num_transp = num_transp + 1
        if isinstance(basset, esdl.Producer) or isinstance(basset, esdl.Conversion) or isinstance(basset, esdl.Storage):
            num_prod_conv_stor = num_prod_conv_stor + 1
        if isinstance(basset, esdl.Consumer):
            num_cons = num_cons + 1

    num_cols = 0
    if num_conns > 0: num_cols = num_cols + 1
    if num_transp > 0: num_cols = num_cols + 1
    if num_prod_conv_stor > 0: num_cols = num_cols + 1
    if num_cons > 0: num_cols = num_cols + 1

    if num_cols > 0:
        column_width = 500 / (num_cols + 1)
        column_idx = 1
        column_conns_x = int(num_conns > 0) * column_idx * column_width
        column_idx += (num_conns > 0)
        column_transp_x = int(num_transp> 0) * column_idx * column_width
        column_idx += (num_transp > 0)
        column_pcs_x = int(num_prod_conv_stor > 0) * column_idx * column_width
        column_idx += (num_prod_conv_stor > 0)
        column_cons_x = int(num_cons > 0) * column_idx * column_width
        column_idx += (num_cons > 0)

        row_conns_height = 500 / (num_conns + 1)
        row_transp_height = 500 / (num_transp + 1)
        row_pcs_height = 500 / (num_prod_conv_stor + 1)
        row_cons_height = 500 / (num_cons + 1)

        row_conns_idx = 1
        row_transp_idx = 1
        row_pcs_idx = 1
        row_cons_idx = 1

        for basset in building.asset:
            if not basset.geometry:
                if isinstance(basset, esdl.AbstractConnection):
                    basset.geometry = esdl.Point(lon=column_conns_x , lat=row_conns_idx * row_conns_height, CRS="Simple")
                    row_conns_idx = row_conns_idx + 1
                elif isinstance(basset, esdl.Transport):
                    basset.geometry = esdl.Point(lon=column_transp_x , lat=row_transp_idx * row_transp_height, CRS="Simple")
                    row_transp_idx = row_transp_idx + 1
                if isinstance(basset, esdl.Producer) or isinstance(basset, esdl.Conversion) or isinstance(basset, esdl.Storage):
                    basset.geometry = esdl.Point(lon=column_pcs_x , lat=row_pcs_idx * row_pcs_height, CRS="Simple")
                    row_pcs_idx = row_pcs_idx + 1
                if isinstance(basset, esdl.Consumer):
                    basset.geometry = esdl.Point(lon=column_cons_x, lat=row_cons_idx * row_cons_height, CRS="Simple")
                    row_cons_idx = row_cons_idx + 1


def update_asset_geometries3(area, boundary):
    if boundary:
        coords = boundary['coordinates']
        type = boundary['type']
        # print(coords)
        # print(type)

        if type == 'Polygon':
            outer_polygon = coords[0]       # Take exterior polygon
        elif type == 'MultiPolygon':
            outer_polygon = coords[0][0]    # Assume first polygon is most relevant and then take exterior polygon
        else:
            send_alert('Non supported polygon')

        center, delta_x, delta_y = calc_center_and_size(outer_polygon)
        # print(center)

    # TODO: An area with a building, with buildingunits (!) with assets is not supported yet
    for asset in area.asset:
        geom = asset.geometry
        if not geom and boundary:
            asset.geometry = calc_random_location_around_center(center, delta_x, delta_y, True)

        if isinstance(asset, esdl.AbstractBuilding):
            calc_building_assets_location(asset)

            # for asset2 in asset.asset:
            #     geom = asset2.geometry
            #     if not geom:
            #         # Building editor uses a 500x500 canvas
            #         asset2.geometry = calc_random_location_around_center([250,250], 500, 500, False)


# ---------------------------------------------------------------------------------------------------------------------
#  Boundary information processing
# ---------------------------------------------------------------------------------------------------------------------
def create_building_KPIs(building):
    KPIs = {}

    try:
        largest_bunit_floorArea = 0
        largest_bunit_type = None

        for basset in building.asset:
            if isinstance(basset, esdl.BuildingUnit):
                if basset.floorArea > largest_bunit_floorArea:
                    largest_bunit_floorArea = basset.floorArea
                    btypes = []
                    for gd in basset.type:
                        btypes.append(gd.name)
                    largest_bunit_type = ", ".join(btypes)

        if largest_bunit_type:
            KPIs["buildingType"] = largest_bunit_type
    except:
        pass

    try:
        if building.buildingYear > 0:
            KPIs["buildingYear"] = building.buildingYear
    except:
        pass

    try:
        if building.floorArea > 0:
            KPIs["floorArea"] = building.floorArea
    except:
        pass

    if building.KPIs:
        for kpi in building.KPIs.kpi:
            KPIs[kpi.name] = kpi.value

    return KPIs


def find_area_info_geojson(building_list, area_list, this_area):
    area_id = this_area.id
    area_name = this_area.name
    if not area_name: area_name = ""
    area_scope = this_area.scope
    area_geometry = this_area.geometry
    boundary_wgs = None

    user = get_session('user-email')
    user_settings = BoundaryService.get_instance().get_user_settings(user)
    boundaries_year = user_settings['boundaries_year']

    geojson_KPIs = {}
    area_KPIs = this_area.KPIs
    if area_KPIs:
        for kpi in area_KPIs.kpi:
            if not isinstance(kpi, esdl.DistributionKPI):
                geojson_KPIs[kpi.name] = kpi.value

    if area_geometry:
        if isinstance(area_geometry, esdl.Polygon):
            boundary_wgs = ESDLGeometry.create_boundary_from_geometry(area_geometry)
            area_list.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    # bug in ESDL genaration with 'get_boundary_info': convert_coordinates_into_subpolygon now
                    # handles order of lat-lon correctly. Exchanging not required anymore
                    # "coordinates": ESDLGeometry.exchange_polygon_coordinates(boundary_wgs['coordinates'])
                    "coordinates": boundary_wgs['coordinates']
                },
                "properties": {
                    "id": area_id,
                    "name": area_name,
                    "KPIs": geojson_KPIs
                }
            })
        if isinstance(area_geometry, esdl.MultiPolygon):
            boundary_wgs = ESDLGeometry.create_boundary_from_geometry(area_geometry)
            for i in range(0, len(boundary_wgs['coordinates'])):
                if len(boundary_wgs['coordinates']) > 1:
                    area_id_number = " ({} of {})".format(i + 1, len(boundary_wgs['coordinates']))
                else:
                    area_id_number = ""
                area_list.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        # bug in ESDL genaration with 'get_boundary_info': convert_coordinates_into_subpolygon now
                        # handles order of lat-lon correctly. Exchanging not required anymore
                        # "coordinates":  ESDLGeometry.exchange_polygon_coordinates(boundary_wgs['coordinates'][i])
                        "coordinates":  boundary_wgs['coordinates'][i]
                    },
                    "properties": {
                        "id": area_id + area_id_number,
                        "name": area_name,
                        "KPIs": geojson_KPIs
                    }
                })
    else:
        # simple hack to check if ID is not a UUID and area_scope is defined --> then query GEIS for boundary
        if area_id and area_scope.name != 'UNDEFINED':
            if len(area_id) < 20:
                # print('Finding boundary from GEIS service')
                boundary_wgs = BoundaryService.get_instance().get_boundary_from_service(boundaries_year, area_scope, str.upper(area_id))
                if boundary_wgs:
                    # this really prevents messing up the cache
                    # tmp = copy.deepcopy(boundary_rd)
                    # tmp['coordinates'] = ESDLGeometry.convert_mp_rd_to_wgs(tmp['coordinates'])    # Convert to WGS
                    # boundary_wgs = tmp
                    for i in range(0, len(boundary_wgs['geom']['coordinates'])):
                        if len(boundary_wgs['geom']['coordinates']) > 1:
                            area_id_number = " ({} of {})".format(i+1, len(boundary_wgs['geom']['coordinates']))
                        else:
                            area_id_number = ""
                        area_list.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": boundary_wgs['geom']['coordinates'][i]
                            },
                            "properties": {
                                "id": str.upper(area_id) + area_id_number,
                                "name": boundary_wgs['name'],
                                "KPIs": geojson_KPIs
                            }
                        })

                    # small hack:
                    # get_boundary_from_service returns different struct than create_boundary_from_geometry
                    boundary_wgs = boundary_wgs['geom']

    # assign random coordinates if boundary is given and area contains assets without coordinates
    # and gives assets within buildings a proper coordinate
    update_asset_geometries3(this_area, boundary_wgs)

    assets = this_area.asset
    for asset in assets:
        if isinstance(asset, esdl.AbstractBuilding):
            pass
            # name = asset.name
            # if not name:
            #     name = ''
            # id = asset.id
            # if not id:
            #     id = ''
            # asset_geometry = asset.geometry
            # if asset_geometry:
            #     if isinstance(asset_geometry, esdl.Polygon):
            #
            #         # Assume this is a building, see if there are buildingUnits to find usage ('gebruiksdoel')
            #         # For now, use first BuildingUnit ...
            #         # TODO: Improve to use most 'dominant' (based on area?) Or introduce 'mixed' category?
            #         KPIs = {}
            #         for basset in asset.asset:
            #             if isinstance(basset, esdl.BuildingUnit):
            #                 try:
            #                     KPIs["buildingType"] = basset.type.name
            #                 except:
            #                     pass
            #
            #         try:
            #             if asset.buildingYear > 0:
            #                 KPIs["buildingYear"] = asset.buildingYear
            #         except:
            #             pass
            #
            #         try:
            #             if asset.floorArea > 0:
            #                 KPIs["floorArea"] = asset.floorArea
            #         except:
            #             pass
            #
            #
            #         bld_boundary = ESDLGeometry.create_boundary_from_contour(asset_geometry)
            #         building_list.append({
            #             "type": "Feature",
            #             "geometry": {
            #                 "type": "Polygon",
            #                 "coordinates": bld_boundary['coordinates']
            #             },
            #             "properties": {
            #                 "id": id,
            #                 "name": name,
            #                 "KPIs": KPIs
            #             }
            #         })
        else: # No AbstractBuilding
            asset_geometry = asset.geometry
            name = asset.name
            if asset_geometry:
               if isinstance(asset_geometry, esdl.WKT):
                        emit('area_boundary', {'info-type': 'WKT', 'boundary': asset_geometry.value,
                                               'crs': asset_geometry.CRS, 'color': 'grey', 'name': name,
                                               'boundary_type': 'asset'})

    potentials = this_area.potential
    for potential in potentials:
        potential_geometry = potential.geometry
        potential_name = potential.name
        if potential_geometry:
            if isinstance(potential_geometry, esdl.WKT):
                # print(potential_geometry)
                emit('pot_boundary', {'info-type': 'WKT', 'boundary': potential_geometry.value,
                                      'crs': potential_geometry.CRS, 'color': 'grey', 'name': potential_name,
                                      'boundary_type': 'potential'})

    areas = this_area.area
    for area in areas:
        find_area_info_geojson(building_list, area_list, area)


def create_area_info_geojson(area):
    building_list = []
    area_list = []
    print("- Finding ESDL boundaries...")
    BoundaryService.get_instance().preload_area_subboundaries_in_cache(area)
    find_area_info_geojson(building_list, area_list, area)
    print("- Done")
    return area_list, building_list


def find_boundaries_in_ESDL(top_area):
    print("Finding area and building boundaries in ESDL")
    # _find_more_area_boundaries(top_area)
    area_list, building_list = create_area_info_geojson(top_area)

    # Sending an empty list triggers removing the legend at client side
    print('- Sending boundary information to client, size={}'.format(getsizeof(area_list)))
    emit('geojson', {"layer": "area_layer", "geojson": area_list})
    print('- Sending asset information to client, size={}'.format(getsizeof(building_list)))
    emit('geojson', {"layer": "bld_layer", "geojson": building_list})


def add_missing_coordinates(area):
    min_lat = float("inf")
    max_lat = -float("inf")
    min_lon = float("inf")
    max_lon = -float("inf")

    for child in area.eAllContents():
        point = None
        if isinstance(child, esdl.Polygon):
            if child.CRS != "Simple": point = child.exterior.point[0]     # take first coordinate of exterior of polygon
        if isinstance(child, esdl.Point):
            if child.CRS != "Simple": point = child
        if point:
            if point.lat < min_lat: min_lat = point.lat
            if point.lat > max_lat: max_lat = point.lat
            if point.lon < min_lon: min_lon = point.lon
            if point.lon > max_lon: max_lon = point.lon
            point = None

    delta_x = max_lon - min_lon
    delta_y = max_lat - min_lat
    center = [(min_lon + max_lon)/2, (min_lat + max_lat)/2]
    RD_coords = (max_lat > 180 and max_lon > 180)               # boolean indicating if RD CRS is used

    for child in area.eAllContents():
        if isinstance(child, esdl.EnergyAsset) or isinstance(child, esdl.AggregatedBuilding) or isinstance(child, esdl.Building):
            if not child.geometry:
                child.geometry = calc_random_location_around_center(center, delta_x / 4, delta_y / 4, RD_coords)


# ---------------------------------------------------------------------------------------------------------------------
#  Process building and process area
# ---------------------------------------------------------------------------------------------------------------------
def process_building(esh, es_id, asset_list, building_list, area_bld_list, conn_list, building, bld_editor, level):
    # Add building to list that is shown in a dropdown at the top
    area_bld_list.append(['Building', building.id, building.name, level])

    # Determine if building has assets
    building_has_assets = False
    if building.asset:
        for basset in building.asset:
            if isinstance(basset, esdl.EnergyAsset):
                building_has_assets = True
                break

    # Generate information for drawing building (as a point or a polygon)
    if isinstance(building, esdl.Building) or isinstance(building, esdl.AggregatedBuilding):
        geometry = building.geometry
        bld_KPIs = create_building_KPIs(building)
        if geometry:
            if isinstance(geometry, esdl.Point):
                building_list.append(
                    ['point', building.name, building.id, type(building).__name__, [geometry.lat, geometry.lon], building_has_assets, bld_KPIs])
                bld_coord = (geometry.lat, geometry.lon)
            elif isinstance(geometry, esdl.Polygon):
                coords = ESDLGeometry.parse_esdl_subpolygon(building.geometry.exterior, False)  # [lon, lat]
                coords = ESDLGeometry.exchange_coordinates(coords)  # --> [lat, lon]
                # building_list.append(['polygon', building.name, building.id, type(building).__name__, coords, building_has_assets])
                boundary = ESDLGeometry.create_boundary_from_geometry(geometry)
                building_list.append(['polygon', building.name, building.id, type(building).__name__, boundary['coordinates'], building_has_assets, bld_KPIs])
                # bld_coord = coords
                bld_coord = ESDLGeometry.calculate_polygon_center(geometry)
    elif building.containingBuilding:       # BuildingUnit
        bld_geom = building.containingBuilding.geometry
        if bld_geom:
            if isinstance(bld_geom, esdl.Point):
                bld_coord = (bld_geom.lat, bld_geom.lon)
            elif isinstance(bld_geom, esdl.Polygon):
                bld_coord = ESDLGeometry.calculate_polygon_center(bld_geom)

    # Iterate over all assets in building to gather all required information
    for basset in building.asset:
        if isinstance(basset, esdl.AbstractBuilding):
            process_building(esh, es_id, asset_list, building_list, area_bld_list, conn_list, basset, bld_editor, level + 1)
        else:
            # Create a list of ports for this asset
            port_list = []
            ports = basset.port
            for p in ports:
                conn_to = p.connectedTo
                conn_to_id_list = [ct.id for ct in conn_to]
                # TODO: add profile_info and carrier
                port_list.append({'name': p.name, 'id': p.id, 'type': type(p).__name__, 'conn_to': conn_to_id_list})

            geom = basset.geometry
            coord = ()
            if geom:    # Individual asset in Building has its own geometry information
                if isinstance(geom, esdl.Point):
                    lat = geom.lat
                    lon = geom.lon
                    coord = (lat, lon)

                    capability_type = ESDLAsset.get_asset_capability_type(basset)
                    if bld_editor:
                        asset_list.append(['point', 'asset', basset.name, basset.id, type(basset).__name__, [lat, lon], port_list, capability_type])
                else:
                    send_alert("Assets within buildings with geometry other than esdl.Point are not supported")

            # Inherit geometry from containing building
            # if level > 0:
            #     coord = bld_coord

            ports = basset.port
            for p in ports:
                p_carr_id = None
                if p.carrier:
                    p_carr_id = p.carrier.id
                conn_to = p.connectedTo
                if conn_to:
                    for pc in conn_to:
                        in_different_buildings = False
                        pc_asset = get_asset_and_coord_from_port_id(esh, es_id, pc.id)

                        # If the asset the current asset connects to, is in a building...
                        if pc_asset['asset'].containingBuilding:
                            bld_pc_asset = pc_asset['asset'].containingBuilding
                            bld_basset = basset.containingBuilding
                            # If the asset is in a different building ...
                            if not bld_pc_asset == bld_basset:
                                in_different_buildings = True
                                if bld_pc_asset.geometry:
                                    if bld_editor:
                                        # ... connect to the left border
                                        pc_asset_coord = (coord[0], 0)
                                    else:
                                        # ... use the building coordinate instead of the asset coordinate
                                        if isinstance(bld_pc_asset.geometry, esdl.Point):
                                            pc_asset_coord = (bld_pc_asset.geometry.lat, bld_pc_asset.geometry.lon)
                                        elif isinstance(bld_pc_asset.geometry, esdl.Polygon):
                                            pc_asset_coord = ESDLGeometry.calculate_polygon_center(bld_pc_asset.geometry)

                                    # If connecting to a building outside of the current, replace current asset
                                    # coordinates with building coordinates too
                                    if not bld_editor:
                                        coord = bld_coord
                            else:
                                # asset is in the same building, use asset's own coordinates
                                pc_asset_coord = pc_asset['coord']
                        else:
                            # other asset is not in a building
                            if bld_editor:
                                # ... connect to the left border
                                pc_asset_coord = (coord[0], 0)
                            else:
                                # ... just use asset's location
                                pc_asset_coord = pc_asset['coord']

                        pc_carr_id = None
                        if pc.carrier:
                            pc_carr_id = pc.carrier.id
                        # Add connections if we're editing a building or if the connection is between two different buildings
                        # ( The case of an asset in an area that is connected with an asset in a building is handled
                        #   in process_area (now all connections are added twice, from both sides) )
                        if bld_editor or in_different_buildings:
                            conn_list.append({'from-port-id': p.id, 'from-port-carrier': p_carr_id, 'from-asset-id': basset.id, 'from-asset-coord': coord,
                                'to-port-id': pc.id, 'to-port-carrier': pc_carr_id, 'to-asset-id': pc_asset['asset'].id, 'to-asset-coord': pc_asset_coord})

    if bld_editor:
        for potential in building.potential:
            geom = potential.geometry
            if geom:
                if isinstance(geom, esdl.Point):
                    lat = geom.lat
                    lon = geom.lon

                    asset_list.append(
                        ['point', 'potential', potential.name, potential.id, type(potential).__name__, [lat, lon]])


def process_area(esh, es_id, asset_list, building_list, area_bld_list, conn_list, area, level):
    area_bld_list.append(['Area', area.id, area.name, level])

    # process subareas
    for ar in area.area:
        process_area(esh, es_id, asset_list, building_list, area_bld_list, conn_list, ar, level+1)

    # process assets in area
    for asset in area.asset:
        if isinstance(asset, esdl.AbstractBuilding):
            process_building(esh, es_id, asset_list, building_list, area_bld_list, conn_list, asset, False, level+1)
        if isinstance(asset, esdl.EnergyAsset):
            port_list = []
            ports = asset.port
            for p in ports:
                p_asset = get_asset_and_coord_from_port_id(esh, es_id, p.id)
                p_asset_coord = p_asset['coord']        # get proper coordinate if asset is line
                conn_to_ids = [cp.id for cp in p.connectedTo]
                profile = p.profile
                profile_info_list = []
                p_carr_id = None
                if p.carrier:
                    p_carr_id = p.carrier.id
                if profile:
                    profile_info_list = generate_profile_info(profile)
                port_list.append({'name': p.name, 'id': p.id, 'type': type(p).__name__, 'conn_to': conn_to_ids, 'profile': profile_info_list, 'carrier': p_carr_id})
                if conn_to_ids:
                    for pc in p.connectedTo:
                        pc_asset = get_asset_and_coord_from_port_id(esh, es_id, pc.id)
                        if pc_asset['asset'].containingBuilding:
                            bld_pc_asset = pc_asset['asset'].containingBuilding
                            if bld_pc_asset.geometry:
                                if isinstance(bld_pc_asset.geometry, esdl.Point):
                                    pc_asset_coord = (bld_pc_asset.geometry.lat, bld_pc_asset.geometry.lon)
                                elif isinstance(bld_pc_asset.geometry, esdl.Polygon):
                                    pc_asset_coord = ESDLGeometry.calculate_polygon_center(bld_pc_asset.geometry)
                        else:
                            pc_asset_coord = pc_asset['coord']

                        pc_carr_id = None
                        if pc.carrier:
                            pc_carr_id = pc.carrier.id
                        conn_list.append({'from-port-id': p.id, 'from-port-carrier': p_carr_id, 'from-asset-id': p_asset['asset'].id, 'from-asset-coord': p_asset_coord,
                                          'to-port-id': pc.id, 'to-port-carrier': pc_carr_id, 'to-asset-id': pc_asset['asset'].id, 'to-asset-coord': pc_asset_coord})

            geom = asset.geometry
            if geom:
                if isinstance(geom, esdl.Point):
                    lat = geom.lat
                    lon = geom.lon

                    capability_type = ESDLAsset.get_asset_capability_type(asset)
                    asset_list.append(['point', 'asset', asset.name, asset.id, type(asset).__name__, [lat, lon], port_list, capability_type])
                if isinstance(geom, esdl.Line):
                    coords = []
                    for point in geom.point:
                        coords.append([point.lat, point.lon])
                    asset_list.append(['line', 'asset', asset.name, asset.id, type(asset).__name__, coords, port_list])
                if isinstance(geom, esdl.Polygon):
                    # if isinstance(asset, esdl.WindParc) or isinstance(asset, esdl.PVParc) or isinstance(asset, esdl.WindPark) or isinstance(asset, esdl.PVPark):
                    coords = ESDLGeometry.parse_esdl_subpolygon(geom.exterior, False)   # [lon, lat]
                    coords = ESDLGeometry.exchange_coordinates(coords)                  # --> [lat, lon]
                    capability_type = ESDLAsset.get_asset_capability_type(asset)
                    # print(coords)
                    asset_list.append(['polygon', 'asset', asset.name, asset.id, type(asset).__name__, coords, port_list, capability_type])

    for potential in area.potential:
        geom = potential.geometry
        if geom:
            if isinstance(geom, esdl.Point):
                lat = geom.lat
                lon = geom.lon

                asset_list.append(
                    ['point', 'potential', potential.name, potential.id, type(potential).__name__, [lat, lon]])
            # if isinstance(geom, esdl.Polygon):
            #     coords = []
            #     for point in geom.point:
            #         coords.append([point.lat, point.lon])
            #     asset_list.append(['line', asset.name, asset.id, type(asset).__name__, coords, port_list])
            if isinstance(geom, esdl.Polygon):
                coords = []

                for point in geom.exterior.point:
                    coords.append([point.lat, point.lon])
                asset_list.append(['polygon', 'potential', potential.name, potential.id, type(potential).__name__, coords])


# ---------------------------------------------------------------------------------------------------------------------
#  Get building information
# ---------------------------------------------------------------------------------------------------------------------
def get_building_information(building):
    asset_list = []
    building_list = []
    bld_list = []
    conn_list = []

    active_es_id = get_session('active_es_id')
    esh = get_handler()

    process_building(esh, active_es_id, asset_list, building_list, bld_list, conn_list, building, True, 0)
    return {
        "id": building.id,
        "asset_list": asset_list,
        "building_list": building_list,
        "aera_bld_list": bld_list,
        "conn_list": conn_list
    }


# ---------------------------------------------------------------------------------------------------------------------
#  Initialization after new or load energy system
#  If this function is run through process_energy_system.submit(filename, es_title) it is executed
#  in a separate thread.
# ---------------------------------------------------------------------------------------------------------------------
def process_energy_system(esh, filename=None, es_title=None, app_context=None, force_update_es_id=None):
    # emit('clear_ui')
    print("Processing energysystems in esh")
    main_es = esh.get_energy_system()

    # 4 June 2020 - Edwin: uncommented following line, we need to check if this is now handled properly
    # set_session('active_es_id', main_es.id)     # TODO: check if required here?
    es_list = esh.get_energy_systems()
    es_info_list = get_session("es_info_list")

    # emit('clear_esdl_layer_list')

    conn_list = []
    mapping = {}
    carrier_list = []
    sector_list = []

    for es in es_list:
        asset_list = []
        building_list = []
        area_bld_list = []
        conn_list = []

        if es.id is None:
            es.id = str(uuid.uuid4())

        if es.id not in es_info_list or es.id == force_update_es_id:
            print("- Processing energysystem with id {}".format(es.id))
            name = es.name
            if not name:
                title = 'Untitled Energysystem'
            else:
                title = name

            emit('create_new_esdl_layer', {'es_id': es.id, 'title': title})
            emit('set_active_layer_id', es.id)

            area = es.instance[0].area
            find_boundaries_in_ESDL(area)       # also adds coordinates to assets if possible
            carrier_list = ESDLEnergySystem.get_carrier_list(es)
            emit('carrier_list', {'es_id': es.id, 'carrier_list': carrier_list})
            sector_list = ESDLEnergySystem.get_sector_list(es)
            if sector_list:
                emit('sector_list', {'es_id': es.id, 'sector_list': sector_list})

            area_kpis = ESDLEnergySystem.process_area_KPIs(area)
            area_name = area.name
            if not area_name:
                area_name = title
            if area_kpis:
                emit('kpis', {'es_id': es.id, 'scope': area_name, 'kpi_list': area_kpis})

            add_missing_coordinates(area)
            process_area(esh, es.id, asset_list, building_list, area_bld_list, conn_list, area, 0)

            emit('add_building_objects', {'es_id': es.id, 'building_list': building_list, 'zoom': False})
            emit('add_esdl_objects', {'es_id': es.id, 'asset_pot_list': asset_list, 'zoom': True})
            emit('area_bld_list', {'es_id': es.id,  'area_bld_list': area_bld_list})
            emit('add_connections', {'es_id': es.id, 'add_to_building': False, 'conn_list': conn_list})

            set_session_for_esid(es.id, 'conn_list', conn_list)
            set_session_for_esid(es.id, 'asset_list', asset_list)
            set_session_for_esid(es.id, 'area_bld_list', area_bld_list)

            # TODO: update asset_list???
            es_info_list[es.id] = {
                "processed": True
            }
        else:
            print("- Energysystem with id {} already processed".format(es.id))

    set_handler(esh)
    # emit('set_active_layer_id', main_es.id)

    #session.modified = True
    print('session variables set', session)
    # print('es_id: ', get_session('es_id'))