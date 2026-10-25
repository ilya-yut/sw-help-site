$(function(){
	if($('[data-toggle="tooltip"]').is('[data-toggle="tooltip"]')) {
		$('[data-toggle="tooltip"]').tooltip();
	}
	
	if($('.header-list').is('.header-list')) {
		$('.header-list .menu-item-has-children>a').on("click", function(event) {
			event.preventDefault();
			$(this).closest('ul').find('.menu-item-has-children ul').not($(this).closest('li').find('ul')).slideUp('300');
			$('.header-list .menu-item-has-children>a').removeClass('active');
			if($(this).closest('li').find('ul').is(':visible')) {
				$(this).removeClass('active');
				$(this).closest('li').find('ul').slideUp('300');
			} else {
				$(this).addClass('active');
				$(this).closest('li').find('ul').slideDown('300');
			}
		});
		document.addEventListener('click', function(event) {
			var e = $('.header-list .menu-item-has-children');
			for(var i=0; i < e.length; i++) {
				if(!e.get(i).contains(event.target)) {
					$(e.get(i)).find('ul').slideUp('300');
					$(e.get(i)).find('a').removeClass('active');
				}
			}
		});
	}

	if($('.category-list').is('.category-list')) {
		$('.category-list li > a').on('click', function(){
			if($(this).closest('li').children('ul').length != 0){
				event.preventDefault();
				if($(this).closest('li').children('ul').is(':visible')) {
					$(this).closest('li').children('ul').slideUp('300');
					$(this).removeClass('active');
					$(this).closest('li').removeClass('current-cat-ancestor');
				} else {
					$(this).closest('li').children('ul').slideDown('300');
					$(this).addClass('active');
					$(this).closest('li').addClass('current-cat-ancestor');
				}
			}
		});
	}

	if($('.category-list_inner').is('.category-list_inner')) {
		$('.category-list_inner li > a').on('click', function(){
			if($(this).closest('li').children('.posts-list').length != 0){
				event.preventDefault();
				if($(this).closest('li').children('.posts-list').is(':visible')) {
					$(this).closest('li').children('.posts-list').slideUp('300');
					$(this).removeClass('active');
					$(this).closest('li').removeClass('current-cat-ancestor');
				} else {
					$(this).closest('li').children('.posts-list').slideDown('300');
					$(this).addClass('active');
					$(this).closest('li').addClass('current-cat-ancestor');
				}
			}
		});
	}

	if($('.clipboard').is('.clipboard')) {
		new ClipboardJS('.clipboard');
	}

	if($('.post-copy__link').is('.post-copy__link')) {
		document.addEventListener('click', function(event) {
			var e = $('.post-copy');
			for(var i=0; i < e.length; i++) {
				if(!e.get(i).contains(event.target)) {
					$(e.get(i)).find('.collapse').collapse('hide');
				}
			}
		});
	}

	if($('.post-search__link').is('.post-search__link')) {
		$('.post-search__link').on('click', function(){
			event.preventDefault();
			$(this).closest('.post-search').addClass('active');
		});
		document.addEventListener('click', function(event) {
			var e = $('.post-search');
			for(var i=0; i < e.length; i++) {
				if(!e.get(i).contains(event.target)) {
					$(e.get(i)).removeClass('active');
				}
			}
		});
	}

	if($('[data-fancybox]').is('[data-fancybox]')) {
		$("[data-fancybox]").fancybox({
			clickContent: false,
			loop: true,
		});
	}

	if($('.post-navbar').is('.post-navbar')) {
		$('.post-categoryes').on('show.bs.collapse', function () {
			$('body').addClass('collaspe-open');
		})
		$('.post-categoryes').on('hide.bs.collapse', function () {
			$('body').removeClass('collaspe-open');
		})
		document.addEventListener('click', function(event) {
			var e = $('.post-categoryes');
			for(var i=0; i < e.length; i++) {
				if(!e.get(i).contains(event.target)) {
					$('.post-categoryes').collapse('hide');
				}
			}
		});
	}

	if($('.ticket-input_file').is('.ticket-input_file')) {
		$('.ticket-input_file').styler({
			fileBrowse: 'Browse',
			filePlaceholder: 'Attach the file',
		});
	}
	if($('.ticket-ch').is('.ticket-ch')) {
		$('.ticket-ch input').styler();
		$('.ticket-ch').styler();
	}
	/*if($("input[type='tel']").is("input[type='tel']")) {
		$("input[type='tel']").mask('+7 (000) 000-00-00');
	}*/

	if($('.owl-carousel').is('.owl-carousel')) {
		$('.owl-carousel').each(function() {
			var changedowl = 0;
			$(this).owlCarousel({
				dots: true,
				loop: true, 
				items: 1,
				margin: 0,
				nav:true,
				navText: false,
				smartSpeed: 1000,
				autoHeight:true,
				onInitialized: function(property) {
					var current = property.item.index;
					var owlTop = $(property.target).find(".owl-item").eq(current).find("img").data('top-label');
					var owlBottom = $(property.target).find(".owl-item").eq(current).find("img").data('bottom-label');
					var descContainer = $(property.target).closest('.owl-carousel').next('.image-caption');
					if(owlTop.length > 0) {
						$(descContainer).text(owlTop);
					} else {
						$(descContainer).text(owlBottom);
					}
				},
				onChanged: function (property) {
					if(changedowl === 0) {changedowl = 1; }
					else {
						var current = property.item.index;
						var owlTop = $(property.target).find(".owl-item").eq(current).find("img").data('top-label');
						var owlBottom = $(property.target).find(".owl-item").eq(current).find("img").data('bottom-label');
						var descContainer = $(property.target).closest('.owl-carousel').next('.image-caption');
						if(owlTop.length > 0) {
							$(descContainer).text(owlTop);
						} else {
							$(descContainer).text(owlBottom);
						}
					}
				}
			});
		});
	}

	/*collapse-content*/
	if($('.collapse-content').is('.collapse-content')) {
		$('.collapse-content__link').on('click', function(){
			event.preventDefault();
			$(this).closest('.collapse-content').find('.collapse-content-body').slideToggle(300);
			$(this).toggleClass('active');
		});
	}

	if($('.category-show-link').is('.category-show-link')) {
		$('.category-show-link').on('click', function(){
			event.preventDefault();
			$(this).closest('.category').find('.cat-item-none-own').slideDown(300);
			$(this).remove();
		});
	}

});