"""Regression checks for the standalone viewer.

Run with: python3 -m unittest discover -s tests -v
Requires Playwright and a local Chromium. AR lifecycle tests simulate WebXR;
real camera tracking and native Android/iOS pickers still need device testing.
"""
import functools
import json
import os
import re
from pathlib import Path
import struct
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def model_fixture():
    positions = struct.pack('<12f', 0, 0, 0, .05, 0, 0, 0, .05, 0, 0, 0, .05)
    indices = struct.pack('<12H', 0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3)
    binary = positions + indices
    doc = {
        'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0, 2, 3]}],
        'nodes': [{'mesh': 0, 'name': 'A', 'children': [1]},
                  {'mesh': 1, 'name': 'B', 'translation': [.1, 0, 0]},
                  {'mesh': 2, 'name': 'C', 'translation': [0, .1, 0]},
                  {'mesh': 3, 'name': 'D', 'translation': [0, 0, .1]}],
        'meshes': [{'name': name, 'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'material': 0}]} for name in 'ABCD'],
        'materials': [{'name': 'Fixture', 'pbrMetallicRoughness': {'baseColorFactor': [.6, .2, .1, 1], 'metallicFactor': 0, 'roughnessFactor': .5}}],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 48}, {'buffer': 0, 'byteOffset': 48, 'byteLength': 24}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 4, 'type': 'VEC3', 'min': [0, 0, 0], 'max': [.05, .05, .05]},
                      {'bufferView': 1, 'componentType': 5123, 'count': 12, 'type': 'SCALAR'}],
    }
    data = json.dumps(doc).encode()
    data += b' ' * (-len(data) % 4)
    return struct.pack('<3I', 0x46546c67, 2, 28 + len(data) + len(binary)) + struct.pack('<2I', len(data), 0x4e4f534a) + data + struct.pack('<2I', len(binary), 0x004e4942) + binary


HOOK = """
  window.__test={panes,slot:()=>panes[0].slots[0],getScene,findModelRoot,collectMeshesAll,
    exportLayerGeometry,launchLayerQueue,launchNativeAR,grpList,arCheckpoint,arReadCheckpoint,arDeleteCheckpoint,
    captureARViews,finishARFileSelection,prepareARFilePicker,launchAR,hideHandoff,
    openRenderHardwareDialog,getARPowerPreference,prepareARSupport,chooseARSupport,
    async names(blob){
      const {GLTFLoader}=await window.__libImport('three/addons/loaders/GLTFLoader.js');
      const gltf=await new GLTFLoader().parseAsync(await blob.arrayBuffer(),'');
      const names=[];gltf.scene.traverse(o=>{if(o.isMesh)names.push(o.name);});return names.sort();
    }
  };
"""
XR_MOCK = """
async () => {
 Object.defineProperty(navigator,'userActivation',{configurable:true,value:{isActive:false}});
 window.__arHandLM={detectForVideo:()=>({landmarks:[]})};
 window.XRWebGLBinding=class{};
 const real=window.__libImport, three=await real('three');
 class Session extends EventTarget {
   async end(){this.dispatchEvent(new Event('end'));}
   async restorePersistentAnchor(){if(!window.__restoreAnchors)throw Error('Unavailable');return {anchorSpace:{},delete(){}};}
   async requestReferenceSpace(type){return {type};}
   async requestHitTestSource(){return {cancel(){}};}
 }
 class Renderer {
   constructor(options){window.__xrOptions=options;this.xr={enabled:true,setReferenceSpaceType(){},async setSession(){},getReferenceSpace(){return {};},getCamera:c=>c};}
   getContext(){return window.__handGl;} setPixelRatio(){} setSize(){} setClearColor(){} dispose(){} render(scene){window.__xrScene=scene;}
   setAnimationLoop(fn){window.__xrFrame=fn;}
 }
 window.__libImport=async spec=>spec==='three'?{...three,WebGLRenderer:Renderer}:real(spec);
 Object.defineProperty(navigator,'xr',{configurable:true,value:{
   isSessionSupported:async()=>true,
   requestSession:async(mode,options)=>{window.__xrRequest=options;const s=new Session();window.__xrSession=s;return s;}
 }});
 window.__xrTick=(time=1000)=>window.__xrFrame?.(time,{
   getViewerPose:()=>({}),getHitTestResults:()=>[{getPose:()=>({transform:{matrix:new three.Matrix4().makeTranslation(2,0,3).elements}})}],getPose:()=>window.__restoreAnchors&&!window.__anchorPoseMissing?{transform:{matrix:new three.Matrix4().makeTranslation(2,0,3).elements}}:null
 });
}
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.playwright = sync_playwright().start()
        launch_env = dict(os.environ)
        if os.environ.get('VIEWER_BROWSER_HOME'):
            launch_env['HOME'] = os.environ['VIEWER_BROWSER_HOME']
        cls.browser = cls.playwright.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--enable-unsafe-swiftshader'], env=launch_env)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.page = self.context.new_page()
        self.errors = []
        self.console = []
        self.page.set_default_timeout(15000)
        self.page.on('console', lambda m: self.console.append(m.text[:400]) if m.type in ['warning', 'error'] else None)
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        source = (ROOT / 'index.html').read_text()
        marker = '  createPane(); activatePane(panes[0]); renderLayout(); buildLayoutPanel();'
        self.assertEqual(source.count(marker), 1)
        source=source.replace(marker,HOOK+marker)
        hand_marker="      const pointerDown=e=>{if(e.target.closest"
        source=source.replace(hand_marker,'''window.__arTest={hand,handProcess,setHand,pickForHand,cameraPoint,captureCam,handAnimate,objects,camera,get selected(){return selected;},configure:(w,h,mode=0)=>{capDW=w;capDH=h;capH=h;handMode=mode;},pixels:()=>capCtx.getImageData(0,0,1,1).data};'''+hand_marker)
        self.page.route(self.url, lambda route: route.fulfill(status=200, content_type='text/html', body=source))
        self.page.goto(self.url, wait_until='networkidle')
        self.page.wait_for_function("customElements.get('model-viewer') && window.__test")

    def tearDown(self):
        if self._outcome.result.errors or self._outcome.result.failures:
            print('Browser diagnostics:', self.console[-8:])
            print('Handoff:', self.page.locator('.ar-handoff').all_text_contents())
            print('Toast:', self.page.locator('#toast').all_text_contents())
        self.context.close()
        self.assertEqual(self.errors, [], 'Unexpected browser exceptions')

    def load_model(self):
        with self.page.expect_file_chooser() as chooser:
            self.page.locator('#placeholder').click()
        chooser.value.set_files({'name': 'assembly.glb', 'mimeType': 'model/gltf-binary', 'buffer': model_fixture()})
        self.page.wait_for_function("__test.slot().viewer?.loaded && __test.slot().viewer.modelIsVisible")
        self.assertEqual(self.page.evaluate("__test.collectMeshesAll(__test.findModelRoot(__test.slot().viewer)).length"), 4)

    def layers(self):
        self.page.get_by_role('button', name='Layers', exact=True).click()
        return self.page.locator('.layer-float:not(.hidden)')

    def group_fixture(self):
        self.page.evaluate("""() => {
          const s=__test.slot(),m=__test.collectMeshesAll(__test.findModelRoot(s.viewer));
          s._meshGroups=[{id:'ab',name:'Group AB',uuids:m.filter(x=>['A','B'].includes(x.name)).map(x=>x.uuid),collapsed:false}];
          s._renderLayerList(s);
        }""")

    def no_table(self):
        self.page.get_by_role('button', name='No, continue without a table', exact=True).click()

    def queue_names(self):
        self.no_table()
        self.page.wait_for_function("document.querySelector('.ar-handoff-go:not([hidden])')")
        return self.page.evaluate("async () => {const state=(await __test.arReadCheckpoint()).state;return __test.names(state.queue[0].sourceBlob);}")

    def test_individual_layer_exports_only_child_without_ancestor(self):
        self.load_model()
        layers = self.layers()
        row = layers.locator('.ly-card').filter(has=self.page.locator('.ly-name', has_text=re.compile(r'^B$')))
        row.get_by_role('button', name='Show only this layer in AR', exact=True).click()
        self.assertEqual(self.queue_names(), ['B'])
        self.assertEqual(self.page.evaluate("__test.collectMeshesAll(__test.findModelRoot(__test.slot().viewer)).filter(m=>m.visible).length"), 4)

    def test_group_and_batch_export_selection_union(self):
        self.load_model()
        layers = self.layers()
        self.group_fixture()
        group = layers.locator('.ly-card.group')
        group.get_by_role('button', name='Show only this group in AR', exact=True).click()
        self.assertEqual(self.queue_names(), ['A', 'B'])
        self.page.get_by_role('button', name='Back to viewer', exact=True).click()
        group.locator('.ly-chk').check()
        layers.locator('.ly-card').filter(has=self.page.locator('.ly-name', has_text=re.compile(r'^C$'))).locator('.ly-chk').check()
        self.assertEqual(layers.locator('.ly-tools button').last.get_attribute('data-ly'), 'ar')
        layers.get_by_role('button', name='Selected layers to AR', exact=True).click()
        self.assertEqual(self.queue_names(), ['A', 'B', 'C'])
        self.page.get_by_role('button', name='Back to viewer', exact=True).click()
        # Partial group deselection must not leave a stale AR group token.
        layers.locator('.ly-card').filter(has=self.page.locator('.ly-name', has_text=re.compile(r'^B$'))).locator('.ly-chk').uncheck()
        layers.get_by_role('button', name='Selected layers to AR', exact=True).click()
        self.assertEqual(self.queue_names(), ['A', 'C'])

    def test_export_hidden_mesh_preserves_visibility_and_transform(self):
        self.load_model()
        result = self.page.evaluate("""async () => {
          const s=__test.slot(),m=__test.collectMeshesAll(__test.findModelRoot(s.viewer)),b=m.find(x=>x.name==='B');
          b.visible=false;const before=b.matrix.toArray();
          const exported=await __test.exportLayerGeometry(s,[{type:'mesh',id:b.uuid}]);
          return {names:await __test.names(exported.sourceBlob),visible:b.visible,same:JSON.stringify(before)===JSON.stringify(b.matrix.toArray())};
        }""")
        self.assertEqual(result, {'names': ['B'], 'visible': False, 'same': True})

    def seed_recovery(self, raw_file=False):
        return self.page.evaluate("""async (raw) => {
          const s=__test.slot(),blob=await s.viewer.exportScene({binary:true,onlyVisible:false});
          const state={items:[{sourceBlob:blob,name:'Previous assembly',placed:true,scaleFactor:1.7,position:{x:1,y:0,z:2},rotation:{x:0,y:.4,z:0}}],queue:[],selectedIndex:0,_needsReposition:true,phase:'picking',views:await __test.captureARViews(s)};
          if(raw){state.phase='converting';state.pendingFiles=[new File(['ply\\nformat ascii 1.0\\nelement vertex 3\\nproperty float x\\nproperty float y\\nproperty float z\\nelement face 1\\nproperty list uchar int vertex_indices\\nend_header\\n0 0 0\\n20 0 0\\n0 20 0\\n3 0 1 2\\n'],'second.ply')];}
          return __test.arCheckpoint(state);
        }""", raw_file)

    def test_reload_and_native_picker_recover_models_and_queue(self):
        self.load_model()
        self.layers()
        self.group_fixture()
        self.assertTrue(self.seed_recovery())
        self.page.reload(wait_until='networkidle')
        self.page.get_by_role('button', name='Choose next file', exact=True).wait_for()
        self.assertTrue(self.page.evaluate('__test.slot().viewer.loaded'))
        self.assertEqual(self.page.evaluate('__test.slot()._meshGroups[0].name'), 'Group AB')
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role('button', name='Choose next file', exact=True).click()
        chooser.value.set_files({'name': 'second.glb', 'mimeType': 'model/gltf-binary', 'buffer': model_fixture()})
        self.no_table()
        self.page.get_by_role('button', name='Continue in AR', exact=True).wait_for()
        self.page.reload(wait_until='networkidle')
        self.page.get_by_role('button', name='Continue in AR', exact=True).wait_for()
        result = self.page.evaluate("async () => {const s=(await __test.arReadCheckpoint()).state;return {items:s.items.length,queue:s.queue.length,position:s.items[0].position,scale:s.items[0].scaleFactor,pending:s.pendingFiles.length};}")
        self.assertEqual(result, {'items': 1, 'queue': 1, 'position': {'x': 1, 'y': 0, 'z': 2}, 'scale': 1.7, 'pending': 0})

    def test_reload_during_conversion_resumes_raw_files(self):
        self.load_model()
        self.assertTrue(self.seed_recovery(raw_file=True))
        self.page.reload(wait_until='networkidle')
        self.no_table()
        self.page.get_by_role('button', name='Continue in AR', exact=True).wait_for(timeout=60000)
        result = self.page.evaluate("async () => {const s=(await __test.arReadCheckpoint()).state;return [s.items.length,s.queue.length,s.queue[0].name,s.pendingFiles.length];}")
        self.assertEqual(result, [1, 1, 'second', 0])

    def test_hardware_preference_changes_new_context_and_persists(self):
        self.load_model()
        self.page.evaluate('__test.openRenderHardwareDialog()')
        dialog = self.page.get_by_role('dialog', name='Rendering hardware')
        self.assertTrue(dialog.locator('[data-hardware-info]').inner_text().startswith('Active WebGL renderer(s):'))
        self.assertTrue(dialog.get_by_label('CPU software rendering unavailable').is_disabled())
        dialog.locator('[data-pref]').select_option('low-power')
        self.assertEqual(self.page.evaluate("document.createElement('canvas').getContext('webgl2').getContextAttributes().powerPreference"), 'low-power')
        self.page.keyboard.press('Escape')
        self.assertEqual(self.page.locator('.viewer-hardware-dialog').count(), 0)
        self.page.reload(wait_until='networkidle')
        self.assertEqual(self.page.evaluate('__test.getARPowerPreference()'), 'low-power')

    def test_native_ar_receives_selected_glb_instead_of_full_viewer(self):
        self.load_model()
        result = self.page.evaluate("""async () => {
          const s=__test.slot(),m=__test.collectMeshesAll(__test.findModelRoot(s.viewer)).find(x=>x.name==='B');
          const request=await __test.exportLayerGeometry(s,[{type:'mesh',id:m.uuid}]);
          const prototype=customElements.get('model-viewer').prototype;
          Object.defineProperty(prototype,'canActivateAR',{configurable:true,get:()=>true});
          await __test.launchNativeAR(s,{items:[],queue:[request]});
          const native=document.querySelector('body > model-viewer');
          return {native:await __test.names(await (await fetch(native.src)).blob()),viewer:__test.collectMeshesAll(__test.findModelRoot(s.viewer)).map(m=>m.name).sort()};
        }""")
        self.assertEqual(result, {'native': ['B'], 'viewer': ['A', 'B', 'C', 'D']})
        self.page.get_by_role('button', name='Back to viewer', exact=True).click()
        self.assertEqual(self.page.locator('body > model-viewer').count(), 0)

    def test_storage_failure_keeps_live_ar_and_does_not_open_picker(self):
        self.load_model()
        self.page.evaluate(XR_MOCK)
        self.page.evaluate("() => { __test.launchAR(__test.slot()); }")
        self.page.locator('html.ar-live').wait_for()
        self.page.wait_for_function("typeof window.__xrFrame === 'function'")
        self.page.evaluate('window.__xrTick()')
        self.page.locator('.stable-ar [data-place]').click()
        self.page.evaluate("""async () => {
          await __test.arReadCheckpoint();
          window.__originalPut=IDBObjectStore.prototype.put;
          IDBObjectStore.prototype.put=function(){throw new DOMException('Simulated full storage','QuotaExceededError');};
        }""")
        self.page.locator('.stable-ar [data-add]').click()
        self.page.wait_for_function("document.querySelector('#toast').textContent.includes('Could not safely open Files')")
        self.assertEqual(self.page.locator('.stable-ar').count(), 1)
        self.assertTrue(self.page.evaluate('__test.slot()._arActive'))
        self.assertIsNone(self.page.evaluate('__test.slot()._arFileInput || null'))
        self.page.evaluate('() => { IDBObjectStore.prototype.put=window.__originalPut; }')
        self.page.locator('.stable-ar [data-exit]').click()

    def test_xr_interruption_picker_cancel_and_explicit_exit(self):
        self.load_model()
        self.page.evaluate(XR_MOCK)
        self.page.evaluate("() => {window.__test.launchAR(__test.slot());}")
        self.page.locator('html.ar-live').wait_for()
        self.page.evaluate('window.__xrTick()')
        self.page.locator('.stable-ar [data-place]').click()
        self.page.locator('.stable-ar [data-add]').click()
        self.page.locator('.ar-pick-folder').click()
        self.assertEqual(self.page.locator('.stable-ar').count(), 1)
        self.page.evaluate("__test.slot()._arFileInput.dispatchEvent(new Event('cancel'))")
        self.assertEqual(self.page.locator('.ar-layer-row').count(), 1)
        self.page.evaluate('window.__xrSession.end()')
        self.page.get_by_role('button', name='Continue in AR', exact=True).wait_for()
        state = self.page.evaluate('async () => (await __test.arReadCheckpoint()).state')
        self.assertEqual(len(state['items']), 1)
        self.assertTrue(state['_needsReposition'])
        self.page.get_by_role('button', name='Continue in AR', exact=True).click()
        self.page.locator('html.ar-live').wait_for()
        self.page.locator('.stable-ar [data-exit]').click()
        self.page.wait_for_function("!document.querySelector('.stable-ar')")
        self.assertIsNone(self.page.evaluate('async () => await __test.arReadCheckpoint()'))

    def start_xr(self):
        self.load_model()
        self.page.evaluate(XR_MOCK)
        self.page.evaluate("() => { __test.launchAR(__test.slot()); }")
        self.page.locator('html.ar-live').wait_for()
        self.page.wait_for_function("typeof window.__xrFrame === 'function'")
        self.page.evaluate('window.__xrTick()')
        self.page.locator('.stable-ar [data-place]').click()

    def add_file_from_xr(self):
        self.page.locator('.stable-ar [data-add]').click()
        with self.page.expect_file_chooser() as chooser:
            self.page.locator('.ar-pick-folder').click()
        chooser.value.set_files({'name':'second.glb','mimeType':'model/gltf-binary','buffer':model_fixture()})
        self.page.get_by_role('dialog',name='Table for the new model',exact=True).wait_for()
        self.assertEqual(self.page.locator('.stable-ar').count(),0)
        self.no_table()
        self.page.get_by_role('button',name='Continue in AR',exact=True).click()
        self.page.locator('html.ar-live').wait_for()
        self.page.wait_for_function("typeof window.__xrFrame === 'function'")
        self.page.evaluate('window.__xrTick()')

    def test_file_add_fallback_places_old_before_new_without_autoplacement(self):
        self.start_xr()
        self.add_file_from_xr()
        self.page.wait_for_function('window.__arTest.objects.length===1')
        self.assertFalse(self.page.evaluate('__arTest.objects[0].placed'))
        self.assertEqual(self.page.locator('.stable-ar [data-place]').inner_text(),'Place previous model')
        self.page.evaluate('window.__xrTick()')
        self.page.locator('.stable-ar [data-place]').click()
        self.page.wait_for_function('__arTest.objects.length===2')
        self.assertEqual(self.page.evaluate('__arTest.objects.map(o=>o.placed)'),[True,False])
        self.assertEqual(self.page.evaluate('__arTest.selected.name'),'second')
        self.assertEqual(self.page.locator('.ar-preflight').count(),0)

    def test_persistent_anchor_restore_leaves_only_new_model_to_place(self):
        self.start_xr()
        self.page.evaluate("__arTest.objects[0].anchorHandle='saved-anchor'")
        self.page.evaluate("window.__restoreAnchors=true")
        self.add_file_from_xr()
        self.page.wait_for_function('__arTest.objects.length===2')
        self.assertEqual(self.page.evaluate('__arTest.objects.map(o=>o.placed)'),[True,False])
        self.assertEqual(self.page.evaluate('__arTest.objects[0].root.position.toArray()'),[2,0,3])
        self.assertEqual(self.page.evaluate('__arTest.selected.name'),'second')

    def test_table_preflight_reuses_objects_controls_and_centers_model(self):
        self.load_model()
        self.page.evaluate("""() => {window.__prepared=(async()=>{
          const s=__test.slot(),b=__test.collectMeshesAll(__test.findModelRoot(s.viewer)).find(m=>m.name==='B');
          return __test.prepareARSupport(await __test.exportLayerGeometry(s,[{type:'mesh',id:b.uuid}]));
        })();}""")
        self.page.get_by_role('button',name='Yes, choose a table',exact=True).click()
        dialog=self.page.get_by_role('dialog',name='Table for the new model',exact=True)
        self.assertEqual(dialog.locator('.object-card').count(),10)
        dialog.get_by_role('button',name='Oak Side Table',exact=True).click()
        dialog.get_by_role('slider',name='Height',exact=True).fill('80')
        dialog.get_by_role('slider',name='Width',exact=True).fill('150')
        dialog.get_by_role('button',name='Continue with this table',exact=True).click()
        result=self.page.evaluate("""async()=>{
          const item=await window.__prepared,T=await __libImport('three'),{GLTFLoader}=await __libImport('three/addons/loaders/GLTFLoader.js');
          const {scene}=await new GLTFLoader().parseAsync(await item.sourceBlob.arrayBuffer(),'');scene.updateMatrixWorld(true);
          const model=new T.Box3(),base=new T.Box3();scene.traverse(m=>{if(m.isMesh)(m.name==='B'?model:base).expandByObject(m,true);});
          const mc=model.getCenter(new T.Vector3()),bc=base.getCenter(new T.Vector3());
          return {dx:mc.x-bc.x,dz:mc.z-bc.z,gap:model.min.y-base.max.y,support:item.support,prepared:item.preflightDone};
        }""")
        self.assertAlmostEqual(result['dx'],0,places=4)
        self.assertAlmostEqual(result['dz'],0,places=4)
        self.assertAlmostEqual(result['gap'],-.0005,places=4)
        self.assertEqual(result['support'],{'key':'oakTable','params':{'height':.8,'margin':1.5}})
        self.assertTrue(result['prepared'])

    def test_hand_proximity_pinch_release_and_checkpoint_home_pose(self):
        self.start_xr()
        self.assertIn('camera-access',self.page.evaluate('__xrRequest.optionalFeatures'))
        result=self.page.evaluate("""() => {
          const h=__arTest,o=h.objects[0];h.configure(640,480);o.root.position.set(0,-.075,-.5);
          const lm=Array.from({length:21},()=>({x:.5,y:.65,z:0}));lm[9]={x:.5,y:.48,z:0};lm[4]={x:.5,y:.5,z:0};lm[8]={x:.501,y:.5,z:0};
          window.__landmarks=lm;h.handProcess({landmarks:[lm]},1000);h.handProcess({landmarks:[lm]},1120);
          return {state:h.hand.state,holding:o._hand,home:o._handHome?.position.toArray()};
        }""")
        self.assertEqual(result,{'state':'grab','holding':True,'home':[0,-.075,-.5]})
        result=self.page.evaluate("""()=>{
          const h=__arTest,lm=__landmarks;lm[4].x=.58;lm[8].x=.581;
          h.handProcess({landmarks:[lm]},1240);h.handAnimate(.1);
          return h.objects[0].root.position.x;
        }""")
        self.assertGreater(result,0)
        # The fixed debounce writes data; it must serialize the home pose, not the lifted pose.
        self.page.wait_for_function("async()=>{const s=await __test.arReadCheckpoint();return s?.state.items?.[0]?.position.z===-.5;}",timeout=7000)
        self.page.evaluate("""()=>{const h=__arTest;h.handProcess({landmarks:[]},2100);for(let i=0;i<40;i++)h.handAnimate(.1);}""")
        self.assertEqual(self.page.evaluate('__arTest.hand.state'),'idle')
        self.assertEqual(self.page.evaluate('__arTest.objects[0].root.position.toArray()'),[0,-.075,-.5])
        result=self.page.evaluate("""()=>{
          const h=__arTest,o=h.objects[0];o.root.position.z=-3;
          h.handProcess({landmarks:[__landmarks]},3000);h.handProcess({landmarks:[__landmarks]},3200);
          return h.hand.state;
        }""")
        self.assertEqual(result,'idle')

    def test_camera_copy_restores_gl_state_and_flips_pixels_upright(self):
        self.start_xr()
        result=self.page.evaluate("""()=>{
          const gl=document.createElement('canvas').getContext('webgl2');window.__handGl=gl;
          const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);
          gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,2,2,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array([255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255]));
          gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
          window.XRWebGLBinding=class{getCameraImage(){return t;}};
          gl.enable(gl.SCISSOR_TEST);gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);gl.scissor(0,0,1,1);gl.colorMask(false,false,false,false);gl.viewport(3,4,17,19);
          __arTest.configure(320,320);const ok=__arTest.captureCam({views:[{camera:{width:2,height:2}}]});
          return {ok,pixel:Array.from(__arTest.pixels()),mask:Array.from(gl.getParameter(gl.COLOR_WRITEMASK)),viewport:Array.from(gl.getParameter(gl.VIEWPORT)),depth:gl.isEnabled(gl.DEPTH_TEST),blend:gl.isEnabled(gl.BLEND),scissor:gl.isEnabled(gl.SCISSOR_TEST),error:gl.getError()};
        }""")
        self.assertEqual(result,{'ok':True,'pixel':[0,0,255,255],'mask':[False]*4,'viewport':[3,4,17,19],'depth':True,'blend':True,'scissor':True,'error':0})

    def test_mobile_toolbar_wrap_and_panels_stay_below_safe_top(self):
        self.page.set_viewport_size({'width':320,'height':700})
        self.start_xr()
        self.page.locator('[data-layers-toggle]').click()
        self.page.wait_for_timeout(150)
        result=self.page.evaluate("""()=>{const t=document.querySelector('.ar-tools').getBoundingClientRect(),l=document.querySelector('.ar-layers').getBoundingClientRect();return {top:t.top,right:t.right,left:t.left,gap:l.top-t.bottom};}""")
        self.assertGreaterEqual(result['top'],34)
        self.assertGreaterEqual(result['left'],0)
        self.assertLessEqual(result['right'],320)
        self.assertGreaterEqual(result['gap'],10)


    def test_table_choice_enters_ar_directly_with_active_user_gesture(self):
        self.start_xr()
        self.page.locator('.stable-ar [data-add]').click()
        with self.page.expect_file_chooser() as chooser:
            self.page.locator('.ar-pick-folder').click()
        chooser.value.set_files({'name':'second.glb','mimeType':'model/gltf-binary','buffer':model_fixture()})
        self.page.get_by_role('dialog',name='Table for the new model',exact=True).wait_for()
        self.page.evaluate("Object.defineProperty(navigator,'userActivation',{configurable:true,value:{isActive:true}})")
        self.no_table()
        self.page.locator('html.ar-live').wait_for()
        self.assertEqual(self.page.locator('.ar-handoff').count(),0)
        self.assertEqual(self.page.evaluate('__arTest.objects.length'),1)

    def test_hand_button_enables_preview_and_reports_denied_camera(self):
        self.start_xr()
        self.page.locator('[data-hand]').click()
        preview=self.page.locator('.ar-hand-preview')
        preview.wait_for()
        self.assertGreaterEqual(preview.locator('canvas').bounding_box()['height'],40)
        self.page.locator('[data-hand]').click()
        self.assertEqual(self.page.locator('.ar-hand-preview').count(),0)
        self.page.evaluate("window.__xrSession.enabledFeatures=[]")
        self.page.locator('[data-hand]').click()
        self.page.wait_for_function("document.querySelector('.ar-message').textContent.includes('did not grant camera access')")
        self.assertEqual(self.page.locator('.ar-hand-preview').count(),0)


    def test_missing_persistent_anchor_pose_falls_back_before_placing_new_model(self):
        self.start_xr()
        self.page.evaluate("__arTest.objects[0].anchorHandle='saved-anchor';window.__restoreAnchors=true;window.__anchorPoseMissing=true")
        self.add_file_from_xr()
        self.assertEqual(self.page.evaluate('__arTest.objects.length'),1)
        self.assertTrue(self.page.evaluate('__arTest.objects[0]._awaitAnchorPose'))
        self.assertFalse(self.page.evaluate('__arTest.objects[0].root.visible'))
        self.page.evaluate('window.__xrTick(10000)')
        self.assertFalse(self.page.evaluate('__arTest.objects[0].placed'))
        self.assertFalse(self.page.evaluate('__arTest.objects[0]._awaitAnchorPose'))
        self.assertEqual(self.page.locator('.stable-ar [data-place]').inner_text(),'Place previous model')
        self.page.locator('.stable-ar [data-place]').click()
        self.page.wait_for_function('__arTest.objects.length===2')
        self.assertEqual(self.page.evaluate('__arTest.objects.map(o=>o.placed)'),[True,False])


if __name__ == '__main__':
    unittest.main()
