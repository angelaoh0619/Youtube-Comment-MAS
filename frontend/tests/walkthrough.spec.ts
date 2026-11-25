import {test,expect,type Page} from '@playwright/test';

const initial='I support a four-day week with the same pay. I assumed it would work for almost everyone.';
const current='I still value a full day off, but I would compare it with shorter daily hours and check who covers the gap.';
const singleId='a'.repeat(32),groupId='b'.repeat(32);
const source={comment_id:'public-source',text:'A full day off and earlier evenings meet different needs.',original_text:'통째로 쉬는 하루와 일찍 퇴근하는 저녁은 쓰임이 다릅니다.',like_count:3,is_reply:false,url:'https://youtube.com/watch?v=BAHKmi4F1L8&lc=public-source'};
const agents=['g1','g2'].map((id,i)=>({agent_id:id,title:i?'Shorter days':'A full day off',subtitle:'A comment perspective',stance:i?'Make ordinary evenings usable.':'Keep a whole day free.',reasoning:'A reason found in comments.',full_stance:'A complete perspective.',statistics:{comment_count:10,comment_share:.5,like_count:3,like_share:.5},arguments:[],variations:[],limitations:[],representative_comments:[source]}));
const message=(id:string,role:string,sender:string,text:string,reply:string|null=null)=>({message_id:id,role,sender_id:sender,text,reply_to:reply,created_at:'2026-11-25T01:00:00Z',language:'en',segments:role==='agent'?[{text,basis:'comment',comment_ids:[source.comment_id]}]:[],evidence:role==='agent'?[source]:[],follow_up_questions:[]});
const single={room_id:singleId,title:'Why a full day off matters',participants:['g1'],initial_opinion:initial,created_at:'2026-11-25T01:00:00Z',updated_at:'2026-11-25T01:00:00Z',paused:true,active_job:null,auto_turns:0,auto_limit:6,message_count:2,preview:'A full day off protects time away from work.',errors:[],messages:[message('m1','user','user','Why does a full day matter?'),message('m2','agent','g1','A full day off protects time away from work.','m1')]};
const group={...single,room_id:groupId,title:'Different needs, different schedules',participants:['g1','g2'],message_count:3,messages:[{...message('m1','user','user','What am I overlooking?'),recipient_ids:['g1','g2']},message('m2','agent','g1','A whole day off can be valuable.','m1'),message('m3','agent','g2','Shorter daily hours may suit regular care responsibilities.','m1')]};
const reflection={before_excerpt:initial,after_excerpt:current,one_to_one:1,group:1,items:[{category:'changed',title:'From one schedule to several options',explanation:'The example now considers different schedules for different needs.',before_quote:'work for almost everyone',now_quote:'compare it with shorter daily hours',moment:{room_id:groupId,message_id:'m3',speaker:'Shorter days',room_type:'group chat',quote:'Shorter daily hours may suit regular care responsibilities.',user_quote:'What am I overlooking?'}},{category:'stayed',title:'Time away from work still matters',explanation:'A full day off remains valuable.',before_quote:'a four-day week',now_quote:'a full day off',moment:null}]};
const catalog={fingerprint:'walkthrough-fixture',video:{video_id:'BAHKmi4F1L8',title:'A shorter working week',url:'https://youtube.com/watch?v=BAHKmi4F1L8'},agents,counts:{collected:20,keep:20,exclude:0,review:0,grouped:20,other:0,likes:6},other_statistics:{comment_count:0,comment_share:0,like_count:0,like_share:0}};

async function mock(page:Page,personalInitial=''){
  const calls:{path:string;method:string;scope:string}[]=[];
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname,scope=req.headers()['x-analysis-id'],method=req.method();calls.push({path,scope,method});
    const reply=(value:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
    if(path==='/api/analyses')return reply({can_analyze:true,analyses:[{analysis_id:'example',is_example:true,has_walkthrough:true,status:'ready',stage:'ready',title:catalog.video.title,video_id:catalog.video.video_id,thumbnail_url:'/assets/videothumbnail.png',collected_count:20,agent_count:2,created_at:'',updated_at:''}]});
    if(path==='/api/bootstrap')return reply(scope==='walkthrough'?{...catalog,read_only:true,is_example:true,account_storage:true,profile:{initial_opinion:initial,saved_evidence:[]},walkthrough:{initial_opinion:initial,current_view:current,default_room_id:singleId,reflection},rooms:[single,group]}:{...catalog,fingerprint:'personal-fixture',is_example:true,account_storage:true,profile:{initial_opinion:personalInitial},rooms:[]});
    if(path==='/api/rooms')return reply(scope==='walkthrough'?[single,group]:[]);
    if(path===`/api/rooms/${singleId}`)return reply(single);
    if(path===`/api/rooms/${groupId}`)return reply(group);
    if(path==='/api/alignment')return reply({job_id:'alignment',status:'completed',result:{agents:agents.map(a=>({agent_id:a.agent_id,score:60,novelty:70,reason:'A shared concern.',new_point:'Different schedules fit different needs.'}))}});
    if(path==='/api/compare')return reply({job_id:'comparison',status:'completed',result:{similar:'A shared concern.',different:'Different priorities.',consideration:'Which schedule fits?',similar_quotes:[],different_quotes:[]}});
    return reply({error:'Unexpected operation'},403);
  });
  return calls;
}

test('completed example opens with a prepared initial view and all later steps ready',async({page})=>{
  const calls=await mock(page);await page.goto('/');
  await page.getByRole('button',{name:'Explore example',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Where this journey began'})).toBeVisible();
  await expect(page.getByRole('textbox',{name:'Your initial view',exact:true})).toHaveValue(initial);
  await expect(page.getByRole('textbox',{name:'Your initial view',exact:true})).toHaveJSProperty('readOnly',true);
  await page.getByRole('button',{name:'Explore these perspectives'}).click();
  await expect(page.locator('.perspective-card')).toHaveCount(2);
  await page.getByTestId('card-g1').click();
  await expect(page.locator('.comparison-section')).toHaveCount(3);
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Read the conversations',exact:true}).click();
  await expect(page.locator('[data-testid="message-agent"]')).toHaveCount(1);
  await expect(page.getByRole('textbox',{name:'Message',exact:true})).toBeHidden();
  await expect(page.locator('.room-delete:visible')).toHaveCount(0);
  await page.locator('.evidence-chip').first().click();
  await expect(page.locator('.evidence-source')).toHaveCount(1);
  await expect(page.locator('.save-evidence')).toBeHidden();
  await page.getByRole('button',{name:'Close evidence panel'}).click();
  await page.getByRole('navigation',{name:'Example journey'}).getByRole('button',{name:'Reflect',exact:true}).click();
  await expect(page.getByRole('heading',{name:'A reflection, connected to the conversation'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'From one schedule to several options'})).toBeVisible();
  await page.getByRole('button',{name:'View this moment'}).click();
  await expect(page.locator('#message-m3 .message')).toHaveClass(/highlight/);
  await expect(page.locator('.conversation-header')).toContainText(group.title);
  await expect(page.getByLabel('Question recipients')).toContainText('To everyone');
  await expect(page.getByLabel('Question recipients').locator('.recipient-chip')).toHaveCount(2);
  const writes=calls.filter(c=>c.scope==='walkthrough'&&c.method!=='GET'&&!['/api/alignment','/api/compare','/api/comments'].includes(c.path));
  expect(writes).toEqual([]);
});

test('a completed reflection survives reload without analysis calls and personal work stays separate',async({page})=>{
  const own='My existing personal initial view.';
  const calls=await mock(page,own);await page.goto('/');
  await page.getByRole('button',{name:'Explore example',exact:true}).click();
  await page.getByRole('navigation',{name:'Example journey'}).getByRole('button',{name:'Reflect',exact:true}).click();
  await page.reload();
  await expect(page.getByRole('heading',{name:'A reflection, connected to the conversation'})).toBeVisible();
  await page.getByRole('button',{name:'Read the full current view'}).click();
  await expect(page.getByRole('textbox',{name:'Your current view'})).toHaveValue(current);
  await expect(page.getByRole('textbox',{name:'Your current view'})).toHaveJSProperty('readOnly',true);
  await page.getByRole('button',{name:'See the completed reflection'}).click();
  expect(calls.filter(c=>c.path==='/api/reflect'||c.path==='/api/reflections'||c.path==='/api/profile')).toEqual([]);
  await page.getByRole('button',{name:'Write your own view',exact:true}).click();
  await expect(page.getByRole('complementary',{name:'Completed example walkthrough'})).toHaveCount(0);
  await page.getByRole('button',{name:'Your initial view',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Edit initial view'})).toHaveValue(own);
});

test('example navigation remains usable on a phone',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mock(page);await page.goto('/');
  await page.getByRole('button',{name:'Explore example',exact:true}).click();
  const nav=page.getByRole('navigation',{name:'Example journey'});
  await expect(nav.getByRole('button')).toHaveCount(4);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
  await nav.getByRole('button',{name:'Reflect',exact:true}).click();
  await expect(page.locator('.review-item')).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
});
